# backend/api/v1/assets/runtime_and_user_js.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, PlainTextResponse
from sqlalchemy.orm import Session as DB
from sqlalchemy import select
from datetime import datetime, timezone

from backend.database import get_db
from backend import models
from backend.services.etag import calc_payload_etag, not_modified, set_etag_header

router = APIRouter(tags=["public:assets"])

RUNTIME_STUB = r"""
;(function(){
  'use strict';

  // ───────── helpers ─────────
  function boot(){ return (window.__PPV_BOOT__||{}); }
  function httpOrigin(){ try{ return location.origin.replace(/\/+$/,''); }catch(_){ return ''; } }
  function wsOrigin(){
    var o = httpOrigin();
    return o.replace(/^http(s?):/i, function(_, s){ return s ? 'wss:' : 'ws:' });
  }
  function api(path){ return (httpOrigin() + path); }
  function clamp(n, a, b){ return Math.max(a, Math.min(n, b)); }

  // ───────── internal state ─────────
  var _state = { ok: null, reason: null, lastCheck: 0 };
  var _subscribers = [];
  var _hbTimer = null;
  var _ws = null;
  var _reconnectAttempt = 0;
  var _checking = false;
  var _autogateStarted = false;

  function emit(){ for (var i=0;i<_subscribers.length;i++){ try{ _subscribers[i](_state); }catch(_){ } } }
  function setState(s){ _state = s; emit(); }

  // ───────── core client-API calls ─────────
  async function callJSON(method, url, body){
    var opts = {
      method: method,
      credentials: 'include',
      headers: { 'Accept':'application/json' }
    };
    if (body != null) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    var res = await fetch(url, opts);
    var data = null; try { data = await res.json(); } catch(_){ data = null; }
    return { ok: res.ok, status: res.status, data: data };
  }
  async function doEnter(eventId){ return callJSON('POST', api('/api/events/' + eventId + '/enter'), {}); }
  async function doHeartbeat(eventId){ return callJSON('POST', api('/api/events/' + eventId + '/heartbeat'), {}); }
  async function doEnsureAccess(eventId){
    var r = await callJSON('GET', api('/api/events/' + eventId + '/ensure-access'), null);
    if (r.status === 404){ var e = await doEnter(eventId); if (!e.ok) return e; return await doHeartbeat(eventId); }
    return r;
  }

  // ───────── ensureAccess orchestration ─────────
  async function _ensureAccess(){
    if (_checking) { while (_checking) { await new Promise(function(res){ setTimeout(res, 30); }); } return { ok: !!_state.ok, reason: _state.reason || undefined }; }
    _checking = true;
    try {
      var evId = boot().eventId;
      if (!evId) return { ok:false, reason:'event_id_missing' };

      var r = await doEnsureAccess(evId);
      var ok = false, reason = null;
      if (r.ok) {
        if (r.data && typeof r.data.ok === 'boolean') { ok = !!r.data.ok; reason = r.data.reason||null; }
        else ok = true;
      } else {
        reason = (r.data && (r.data.reason || r.data.detail)) ||
                 (r.status === 401 ? 'event_token_missing' :
                  r.status === 403 ? 'not_allowed' : 'forbidden');
      }

      _state = { ok: ok, reason: reason, lastCheck: Date.now() }; emit();

      if (ok) { startHeartbeat(); ensureWSConnected(); } else { stopHeartbeat(); closeWS(); }
      return { ok: ok, reason: reason||undefined };
    } catch(_e) {
      _state = { ok:false, reason:'network_error', lastCheck: Date.now() }; emit(); stopHeartbeat(); closeWS();
      return { ok:false, reason:'network_error' };
    } finally {
      _checking = false;
    }
  }

  // ───────── heartbeat management ─────────
  function stopHeartbeat(){ if (_hbTimer){ try{ clearInterval(_hbTimer); }catch(_){ } _hbTimer = null; } }
  function startHeartbeat(){
    stopHeartbeat();
    var evId = boot().eventId; if (!evId) return;
    (async function(){ var r = await doHeartbeat(evId); if (!r.ok){ var reason=(r.data&&(r.data.reason||r.data.detail))||'heartbeat_denied'; setState({ ok:false, reason:reason, lastCheck: Date.now() }); stopHeartbeat(); closeWS(); } })();
    _hbTimer = setInterval(async function(){
      var r = await doHeartbeat(evId);
      if (!r.ok){ var reason=(r.data&&(r.data.reason||r.data.detail))||'heartbeat_denied'; setState({ ok:false, reason:reason, lastCheck: Date.now() }); stopHeartbeat(); closeWS(); }
    }, 10000);
  }
  document.addEventListener('visibilitychange', function(){
    if (document.visibilityState !== 'visible') return;
    var evId = boot().eventId; if (!evId) return;
    (async function(){
      try { var e=await doEnter(evId); var h=await doHeartbeat(evId); var ok=(e.ok && h.ok);
        setState({ ok: ok, reason: ok? null : (h.data&&h.data.reason)||'network_error', lastCheck: Date.now() });
        if (ok) { startHeartbeat(); ensureWSConnected(); } else { stopHeartbeat(); closeWS(); }
      } catch(_){ setState({ ok:false, reason:'network_error', lastCheck: Date.now() }); }
    })();
  });

  // ───────── session WS ─────────
  function closeWS(){ try{ if (_ws){ _ws.close(); } }catch(_){ } _ws = null; }
  function ensureWSConnected(){
    if (_ws && _ws.readyState === WebSocket.OPEN) return;
    var url = wsOrigin() + '/api/ws/client';
    try { _ws = new WebSocket(url); } catch(_){ scheduleReconnect(); return; }
    _ws.onopen = function(){ _reconnectAttempt = 0; };
    _ws.onmessage = function(evt){
      try {
        var msg = JSON.parse(evt.data);
        if (msg && (msg.type==='terminate' || msg.type==='session_logout' || msg.type==='admin_logout')){
          try{ var v=document.querySelector('video'); if (v && typeof v.pause==='function') v.pause(); }catch(_){}
          setState({ ok:false, reason:'session_invalid', lastCheck: Date.now() }); stopHeartbeat();
        }
      } catch(_){}
    };
    _ws.onerror = function(){};
    _ws.onclose = function(){ if (_state && _state.ok===false) return; scheduleReconnect(); };
  }
  function scheduleReconnect(){
    var attempt = (_reconnectAttempt = (_reconnectAttempt||0)+1);
    var delay = clamp(Math.pow(2, attempt)*250, 500, 10000);
    setTimeout(function(){ try{ ensureWSConnected(); }catch(_){ } }, delay);
  }

  // ───────── minimal player ─────────
  function mountPlayer(elOrSelector, opts){
    var el = (typeof elOrSelector==='string')? document.querySelector(elOrSelector) : elOrSelector;
    if (!el){ console.warn('PPV.player.mount: element not found', elOrSelector); return { destroy: function(){} }; }
    var src = opts && (opts.src || opts.manifest || opts.url); if (!src){ console.warn('PPV.player.mount: src required'); return { destroy: function(){} }; }
    var video = document.createElement('video'); video.setAttribute('controls',''); video.setAttribute('playsinline',''); video.style.width='100%'; video.style.height='100%'; video.style.background='#000';
    try{
      if (window.Hls && window.Hls.isSupported()){
        var hls = new window.Hls({ enableWorker:true }); hls.loadSource(src); hls.attachMedia(video);
        el.innerHTML=''; el.appendChild(video);
        return { destroy: function(){ try{ hls.destroy(); }catch(_){ } try{ el.innerHTML=''; }catch(_){ } } };
      } else {
        var source=document.createElement('source'); source.src=src; source.type='application/x-mpegURL'; video.appendChild(source);
        el.innerHTML=''; el.appendChild(video);
        return { destroy: function(){ try{ el.innerHTML=''; }catch(_){ } } };
      }
    } catch(e){ console.warn('PPV.player.mount error:', e); el.innerHTML='<div style="padding:12px;border:1px solid #333;color:#bbb">Плеєр недоступний</div>'; return { destroy:function(){ try{ el.innerHTML=''; }catch(_){ } } }; }
  }

  // ───────── public API ─────────
  var PPV = window.PPV = window.PPV || {};
  PPV.env = PPV.env || (boot().env || {});
  PPV.analytics = PPV.analytics || { track: function(ev, props){ try{ console.log('[analytics]', ev, props||{}); }catch(_){ } } };
  PPV.ui = PPV.ui || { toast: function(msg){ try{ console.log('[toast]', msg); }catch(_){ } } };
  PPV.player = PPV.player || {}; PPV.player.mount = function(el, opts){ return mountPlayer(el, opts||{}); };
  PPV.session = PPV.session || {};
  PPV.session.ensureAccess = _ensureAccess;
  PPV.session.onChange = function(cb){ if (typeof cb==='function'){ _subscribers.push(cb); } return function(){ var i=_subscribers.indexOf(cb); if(i>=0) _subscribers.splice(i,1); }; };

  // ───────── AUTO-GATE (вмикається за замовчуванням) ─────────
  async function autoGate(){
    if (_autogateStarted) return; _autogateStarted = true;
    // Перевірка доступу
    var res = await _ensureAccess();
    if (!res.ok){
      var here = location.pathname + location.search + location.hash;
      var login = (boot().loginPath || '/login');
      var reason = res.reason || 'event_token_missing';
      location.replace(login + '?redirect=' + encodeURIComponent(here) + '&reason=' + encodeURIComponent(reason));
      return;
    }
    // Доступ підтверджено — прибираємо "gated"
    try { document.documentElement.classList.remove('gated'); document.body.classList.remove('gated'); } catch(_){}
    // Реакція на миттєвий логаут
    PPV.session.onChange(function(st){
      if (st && st.ok===false){
        try{ var v=document.querySelector('video'); v && v.pause(); }catch(_){}
        var here = location.pathname + location.search + location.hash;
        var login = (boot().loginPath || '/login');
        var reason = st.reason || 'session_invalid';
        location.replace(login + '?redirect=' + encodeURIComponent(here) + '&reason=' + encodeURIComponent(reason));
      }
    });
  }

  if (boot().autoGate !== false) {
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', autoGate, { once:true }); }
    else { autoGate(); }
  }

  // для дебагу
  PPV._debug = { state:function(){return _state;}, forceEnsure:function(){return _ensureAccess();}, stopHeartbeat:stopHeartbeat, startHeartbeat:startHeartbeat };

})();
"""



@router.get("/event-assets/{event_id}/user.js")
def event_user_js(event_id: int, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")

    content = (ev.page_js or "").strip()
    # ETag залежить від контенту і updated_at
    etag = calc_payload_etag("user.js", event_id, ev.updated_at or "", len(content))
    headers = {"Cache-Control": "public, max-age=300"}
    set_etag_header(headers, etag)
    return Response(content=content, media_type="application/javascript; charset=utf-8", headers=headers)

@router.get("/runtime/ppv-runtime.{version}.js")
def ppv_runtime(version: str):
    # У проді краще віддавати статичний зібраний файл із CDN
    headers = {"Cache-Control": "public, max-age=3600"}
    return PlainTextResponse(RUNTIME_STUB, media_type="application/javascript; charset=utf-8", headers=headers)
