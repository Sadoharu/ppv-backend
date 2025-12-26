from __future__ import annotations

# 1. Generic/Shared
from .shared import Page

# 2. Auth (Admin + Client)
from .auth import (
    LoginRequest,
    TokenResponse,
    AdminLogin,
    AdminToken,
)

# 3. Access Codes
from .access_codes import (
    AccessCodeOut,
    AccessCodeCreate,
    AccessCodePatch,
    BulkDeleteCodes,
)

# 4. Sessions
from .sessions import (
    SessionOut,
    BulkDeleteSessions,
)

# 5. Events (Base)
from .events import (
    EventStatus,
    CustomMode,
    EventCreate,
    EventUpdate,
    EventOut,
    EventOutShort,
)

# 6. Event Pages (Custom)
from .event_page import (
    EventPageUpdate,
    EventPageOut,
)

# 7. Admin Users
from .admin_users import (
    AdminUserCreate,
    AdminUserUpdate,
    AdminUserResponse,
)

# 8. Analytics
from .analytics import (
    CcuPoint,
    CodeStats,
)