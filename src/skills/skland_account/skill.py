from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx


SKLAND_HEADERS = {
    "User-Agent": "Skland/1.32.1 (com.hypergryph.skland; build:103201004; Android 33; ) Okhttp/4.11.0",
    "Accept-Encoding": "gzip",
    "Connection": "close",
}
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"
SKLAND_BASE_URL = "https://zonai.skland.com/api/v1"
SKLAND_DATA_FILE = Path("data") / "skland_accounts.json"
TIMEOUT = 20.0
SCAN_TIMEOUT_SECONDS = 100


class SklandError(RuntimeError):
    pass


@dataclass(slots=True)
class SklandCred:
    cred: str
    token: str
    user_id: str | None = None


@dataclass(slots=True)
class BoundRole:
    uid: str
    nickname: str
    server_name: str
    server_id: str
    role_id: str
    is_default: bool


@dataclass(slots=True)
class StoredAccount:
    qq_user_id: str
    access_token: str = ""
    cred: str = ""
    cred_token: str = ""
    skland_user_id: str = ""
    roles: list[BoundRole] = field(default_factory=list)
    default_uid: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class BindResult:
    message: str
    role_count: int
    default_uid: str


@dataclass(slots=True)
class SklandAccountSummary:
    nickname: str
    uid: str
    level: int
    main_stage: str
    ap_current: int
    ap_max: int
    char_count: int
    skin_count: int
    furniture_count: int
    secretary_name: str
    assist_names: list[str]
    role_nickname: str
    role_server: str

    def to_text(self) -> str:
        assist = "、".join(self.assist_names) if self.assist_names else "无"
        return (
            f"森空岛账号摘要\n"
            f"博士名：{self.nickname}\n"
            f"UID：{self.uid}\n"
            f"等级：{self.level}\n"
            f"主线：{self.main_stage}\n"
            f"理智：{self.ap_current}/{self.ap_max}\n"
            f"干员数：{self.char_count}，时装：{self.skin_count}，家具：{self.furniture_count}\n"
            f"助理：{self.secretary_name or '未知'}\n"
            f"助战：{assist}\n"
            f"当前角色：{self.role_nickname} @ {self.role_server}"
        )


def _load_store() -> dict[str, StoredAccount]:
    if not SKLAND_DATA_FILE.exists():
        return {}
    try:
        raw = json.loads(SKLAND_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    accounts: dict[str, StoredAccount] = {}
    for qq_user_id, item in raw.items():
        roles = [BoundRole(**role) for role in item.get("roles", [])]
        accounts[qq_user_id] = StoredAccount(
            qq_user_id=qq_user_id,
            access_token=item.get("access_token", ""),
            cred=item.get("cred", ""),
            cred_token=item.get("cred_token", ""),
            skland_user_id=item.get("skland_user_id", ""),
            roles=roles,
            default_uid=item.get("default_uid", ""),
            updated_at=item.get("updated_at", ""),
        )
    return accounts


def _save_store(store: dict[str, StoredAccount]) -> None:
    SKLAND_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {qq_user_id: asdict(account) for qq_user_id, account in store.items()}
    SKLAND_DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def bind_account_by_scan_token(qq_user_id: str, token: str) -> BindResult:
    grant_code = await _get_grant_code(token, 0)
    cred = await _get_cred(grant_code)
    account = StoredAccount(
        qq_user_id=qq_user_id,
        access_token=token,
        cred=cred.cred,
        cred_token=cred.token,
        skland_user_id=cred.user_id or "",
    )
    roles, default_uid = await _fetch_roles(account)
    account.roles = roles
    account.default_uid = default_uid
    account.updated_at = _now_text()
    store = _load_store()
    store[qq_user_id] = account
    _save_store(store)
    return BindResult("扫码绑定成功。", len(roles), default_uid)


def unbind_account(qq_user_id: str) -> bool:
    store = _load_store()
    if qq_user_id not in store:
        return False
    del store[qq_user_id]
    _save_store(store)
    return True


async def refresh_roles(qq_user_id: str) -> BindResult:
    store = _load_store()
    account = _get_account(store, qq_user_id)
    account = await _ensure_fresh_tokens(account)
    roles, default_uid = await _fetch_roles(account)
    account.roles = roles
    account.default_uid = default_uid
    account.updated_at = _now_text()
    store[qq_user_id] = account
    _save_store(store)
    return BindResult("角色列表已刷新。", len(roles), default_uid)


def list_roles(qq_user_id: str) -> list[BoundRole]:
    return _get_account(_load_store(), qq_user_id).roles


def format_roles(roles: list[BoundRole]) -> str:
    if not roles:
        return "当前没有绑定到可用的明日方舟角色。"
    lines = ["已绑定角色："]
    for role in roles:
        default_mark = " [默认]" if role.is_default else ""
        lines.append(f"- {role.nickname} | UID {role.uid} | {role.server_name}{default_mark}")
    return "\n".join(lines)


async def get_account_summary(qq_user_id: str) -> SklandAccountSummary:
    store = _load_store()
    account = _get_account(store, qq_user_id)
    account = await _ensure_fresh_tokens(account)
    if not account.default_uid:
        roles, default_uid = await _fetch_roles(account)
        account.roles = roles
        account.default_uid = default_uid
        store[qq_user_id] = account
        _save_store(store)

    card = await _get_ark_card(SklandCred(cred=account.cred, token=account.cred_token), account.default_uid)
    status = card.get("status") or {}
    char_info_map = card.get("charInfoMap") or {}
    secretary = status.get("secretary") or {}
    secretary_name = (char_info_map.get(secretary.get("charId")) or {}).get("name", "")
    role = _pick_default_role(account.roles, account.default_uid)
    assist_names = []
    for assist in card.get("assistChars") or []:
        name = (char_info_map.get(assist.get("charId")) or {}).get("name")
        if name:
            assist_names.append(name)

    ap = status.get("ap") or {}
    return SklandAccountSummary(
        nickname=status.get("name", role.nickname if role else ""),
        uid=status.get("uid", account.default_uid),
        level=int(status.get("level") or 0),
        main_stage=status.get("mainStageProgress", "未知"),
        ap_current=_calc_ap_now(ap),
        ap_max=int(ap.get("max") or 0),
        char_count=int(status.get("charCnt") or 0),
        skin_count=int(status.get("skinCnt") or 0),
        furniture_count=int(status.get("furnitureCnt") or 0),
        secretary_name=secretary_name,
        assist_names=assist_names[:3],
        role_nickname=role.nickname if role else "",
        role_server=role.server_name if role else "",
    )


async def create_scan_id() -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://as.hypergryph.com/general/v1/gen_scan/login",
            json={"appCode": SKLAND_APP_CODE},
        )
    data = response.json()
    if data.get("status") not in (None, 0):
        raise SklandError(f"获取森空岛登录二维码失败：{data.get('msg', '未知错误')}")
    return str((data.get("data") or {}).get("scanId") or "")


async def poll_scan_code(scan_id: str) -> str | None:
    end_time = datetime.now().timestamp() + SCAN_TIMEOUT_SECONDS
    while datetime.now().timestamp() < end_time:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                "https://as.hypergryph.com/general/v1/scan_status",
                params={"scanId": scan_id},
            )
        data = response.json()
        if data.get("status") in (None, 0):
            scan_code = str((data.get("data") or {}).get("scanCode") or "")
            if scan_code:
                return scan_code
        await asyncio.sleep(2)
    return None


async def get_token_by_scan_code(scan_code: str) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://as.hypergryph.com/user/auth/v1/token_by_scan_code",
            json={"scanCode": scan_code},
        )
    data = response.json()
    if data.get("status") not in (None, 0):
        raise SklandError(f"扫码换取 token 失败：{data.get('msg', '未知错误')}")
    return str((data.get("data") or {}).get("token") or "")


def _get_account(store: dict[str, StoredAccount], qq_user_id: str) -> StoredAccount:
    account = store.get(qq_user_id)
    if not account:
        raise SklandError("你还没有绑定森空岛。")
    return account


async def _ensure_fresh_tokens(account: StoredAccount) -> StoredAccount:
    try:
        account.cred_token = await _refresh_cred_token(account.cred)
    except SklandError as exc:
        if not account.access_token:
            raise SklandError(f"森空岛凭证已失效：{exc}")
        grant_code = await _get_grant_code(account.access_token, 0)
        cred = await _get_cred(grant_code)
        account.cred = cred.cred
        account.cred_token = cred.token
        account.skland_user_id = cred.user_id or account.skland_user_id

    account.updated_at = _now_text()
    store = _load_store()
    store[account.qq_user_id] = account
    _save_store(store)
    return account


async def _fetch_roles(account: StoredAccount) -> tuple[list[BoundRole], str]:
    binding_apps = await _get_binding(SklandCred(cred=account.cred, token=account.cred_token))
    roles: list[BoundRole] = []
    default_uid = ""
    for app in binding_apps:
        for character in app.get("bindingList") or []:
            uid = str(character.get("uid") or "")
            character_default = bool(character.get("isDefault"))
            role_items = character.get("roles") or []
            if role_items:
                for role in role_items:
                    bound_role = BoundRole(
                        uid=uid,
                        nickname=str(role.get("nickname") or character.get("nickName") or ""),
                        server_name=str(role.get("serverName") or character.get("channelName") or ""),
                        server_id=str(role.get("serverId") or character.get("channelMasterId") or ""),
                        role_id=str(role.get("roleId") or ""),
                        is_default=bool(role.get("isDefault")) or (len(role_items) == 1 and character_default),
                    )
                    roles.append(bound_role)
                    if bound_role.is_default and not default_uid:
                        default_uid = uid
            else:
                roles.append(
                    BoundRole(
                        uid=uid,
                        nickname=str(character.get("nickName") or ""),
                        server_name=str(character.get("channelName") or ""),
                        server_id=str(character.get("channelMasterId") or ""),
                        role_id="",
                        is_default=character_default,
                    )
                )
                if character_default and not default_uid:
                    default_uid = uid
    if not default_uid and roles:
        roles[0].is_default = True
        default_uid = roles[0].uid
    return roles, default_uid


def _pick_default_role(roles: list[BoundRole], default_uid: str) -> BoundRole | None:
    for role in roles:
        if role.is_default or role.uid == default_uid:
            return role
    return roles[0] if roles else None


async def _get_grant_code(token: str, grant_type: int) -> str:
    payload = {"appCode": SKLAND_APP_CODE, "token": token, "type": grant_type}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://as.hypergryph.com/user/oauth2/v2/grant",
            json=payload,
            headers=SKLAND_HEADERS,
        )
    data = response.json()
    if data.get("status") not in (None, 0):
        raise SklandError(f"获取认证代码失败：{data.get('msg', '未知错误')}")
    return data["data"]["code"]


async def _get_cred(grant_code: str) -> SklandCred:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code",
            json={"code": grant_code, "kind": 1},
            headers=SKLAND_HEADERS,
        )
    data = response.json()
    if data.get("status") not in (None, 0):
        raise SklandError(f"获取 cred 失败：{data.get('message') or data.get('messgae') or '未知错误'}")
    payload = data.get("data") or {}
    return SklandCred(
        cred=str(payload.get("cred") or ""),
        token=str(payload.get("token") or ""),
        user_id=str(payload.get("userId") or ""),
    )


async def _refresh_cred_token(cred: str) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(
            "https://zonai.skland.com/api/v1/auth/refresh",
            headers={**SKLAND_HEADERS, "cred": cred},
        )
    data = response.json()
    if data.get("status") not in (None, 0):
        raise SklandError(f"刷新 cred_token 失败：{data.get('message', '未知错误')}")
    return str((data.get("data") or {}).get("token") or "")


async def _get_user_id(cred: SklandCred) -> str:
    url = f"{SKLAND_BASE_URL}/user/teenager"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_get_sign_header(cred, url, "get"))
    data = response.json()
    _raise_if_code_error(data, "获取森空岛 user_id 失败")
    return str((((data.get("data") or {}).get("teenager") or {}).get("userId")) or "")


async def _get_binding(cred: SklandCred) -> list[dict]:
    url = f"{SKLAND_BASE_URL}/game/player/binding"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_get_sign_header(cred, url, "get"))
    data = response.json()
    _raise_if_code_error(data, "获取绑定角色失败")
    return list((((data.get("data") or {}).get("list")) or []))


async def _get_ark_card(cred: SklandCred, uid: str) -> dict:
    url = f"{SKLAND_BASE_URL}/game/player/info?uid={uid}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, headers=_get_sign_header(cred, url, "get"))
    data = response.json()
    _raise_if_code_error(data, "获取角色卡片失败")
    return dict(data.get("data") or {})


def _raise_if_code_error(data: dict, prefix: str) -> None:
    code = data.get("code")
    if code in (None, 0):
        return
    raise SklandError(f"{prefix}：{data.get('message', '未知错误')}")


def _get_sign_header(cred: SklandCred, url: str, method: str, query_body: dict | None = None) -> dict[str, str]:
    timestamp = int(datetime.now().timestamp()) - 1
    header_for_sign = {"platform": "", "timestamp": str(timestamp), "dId": "", "vName": ""}
    parsed_url = urlparse(url)
    query_params = json.dumps(query_body) if method == "post" and query_body is not None else parsed_url.query
    header_ca_str = json.dumps(header_for_sign, separators=(",", ":"))
    secret = f"{parsed_url.path}{query_params}{timestamp}{header_ca_str}"
    hex_secret = hmac.new(cred.token.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()
    signature = hashlib.md5(hex_secret.encode("utf-8")).hexdigest()
    return {"cred": cred.cred, **SKLAND_HEADERS, "sign": signature, **header_for_sign}


def _calc_ap_now(ap: dict) -> int:
    current = int(ap.get("current") or 0)
    ap_max = int(ap.get("max") or 0)
    recovery = int(ap.get("completeRecoveryTime") or 0)
    if not ap_max or not recovery:
        return current
    current_ts = datetime.now().timestamp()
    recovered = ap_max - max(int((recovery - current_ts) / 360 + 0.9999), 0)
    return min(max(recovered, current), ap_max)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
