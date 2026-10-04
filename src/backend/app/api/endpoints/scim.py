"""SCIM 2.0 (RFC 7643, 7644): the organization's IdP, such as Okta or Entra ID,
pushes its users and groups here and keeps them in sync. It signs in with the
organization's SCIM token. A user's groups set their role through the IdP's
role rules; a user the IdP deactivates or deletes can't sign in any more."""

import hashlib
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.directory import assign_role, deactivate, record
from app.db.models import DirectoryGroup, Organization, User
from app.db.sandbox import outside_sandboxes
from app.db.session import get_session

router = APIRouter(prefix="/scim/v2", tags=["scim"])

Session = Annotated[AsyncSession, Depends(get_session)]

USER = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
MEDIA = "application/scim+json"


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None):
        self.status, self.detail, self.scim_type = status, detail, scim_type


def scim(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=MEDIA)


def error(e: ScimError) -> JSONResponse:
    body: dict[str, Any] = {
        "schemas": [ERROR],
        "status": str(e.status),
        "detail": e.detail,
    }
    if e.scim_type:
        body["scimType"] = e.scim_type
    return scim(body, e.status)


async def scim_org(
    session: Session, authorization: Annotated[str | None, Header()] = None
) -> Organization:
    """The organization whose SCIM token the IdP sends."""
    scheme, _, token = (authorization or "").partition(" ")
    digest = hashlib.sha256(token.strip().encode()).hexdigest()
    org = None
    if scheme.lower() == "bearer" and token.strip():
        org = await session.scalar(
            select(Organization).where(Organization.scim_token_hash == digest)
        )
    if org is None:
        raise ScimError(401, "Unknown SCIM token")
    return org


Org = Annotated[Organization, Depends(scim_org)]


async def body_of(request: Request) -> dict[str, Any]:
    """The JSON body, whatever its media type: IdPs send application/scim+json."""
    try:
        body = await request.json()
    except ValueError as e:
        raise ScimError(400, "The body is not JSON", "invalidSyntax") from e
    if not isinstance(body, dict):
        raise ScimError(400, "The body is not an object", "invalidSyntax")
    return body


def equals_filter(filter: str | None, attribute: str) -> str | None:
    """The value of a `<attribute> eq "value"` filter, the only kind IdPs send
    when they look a user or group up."""
    if not filter:
        return None
    found = re.fullmatch(rf'\s*{attribute}\s+eq\s+"([^"]*)"\s*', filter, re.IGNORECASE)
    if found is None:
        raise ScimError(
            400, f"Only {attribute} eq filters are supported", "invalidFilter"
        )
    return found.group(1)


def listing(resources: list[dict[str, Any]], total: int, start: int) -> JSONResponse:
    return scim(
        {
            "schemas": [LIST],
            "totalResults": total,
            "startIndex": start,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }
    )


# Users


def user_resource(user: User) -> dict[str, Any]:
    given, _, family = user.name.partition(" ")
    resource: dict[str, Any] = {
        "schemas": [USER],
        "id": str(user.id),
        "userName": user.email,
        "displayName": user.name,
        "name": {"givenName": given, "familyName": family, "formatted": user.name},
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": user.active,
        "meta": {"resourceType": "User", "location": f"/scim/v2/Users/{user.id}"},
    }
    if user.external_id:
        resource["externalId"] = user.external_id
    return resource


def apply_user(user: User, body: dict[str, Any]) -> None:
    """Takes the attributes the IdP sends: userName, the primary email, the
    name, externalId and active."""
    emails = body.get("emails") or []
    primary = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
    email = str(body.get("userName") or primary.get("value") or user.email or "")
    if "@" not in email:
        raise ScimError(400, "userName must be an email", "invalidValue")
    user.email = email.strip().lower()
    name = body.get("name") or {}
    full = name.get("formatted") or " ".join(
        part for part in (name.get("givenName"), name.get("familyName")) if part
    )
    user.name = body.get("displayName") or full or user.name or user.email
    if "externalId" in body:
        user.external_id = body["externalId"]


async def own_user(session: AsyncSession, org: Organization, id: str) -> User:
    try:
        user = await session.get(User, uuid.UUID(id))
    except ValueError:
        user = None
    if user is None or user.org_id != org.id:
        raise ScimError(404, f"No user {id}")
    return user


async def set_active(session: AsyncSession, user: User, active: bool) -> None:
    if active:
        if user.active is False:
            record(session, user, "reactivated")
        user.active = True
    else:
        await deactivate(session, user)


@router.get("/Users", summary="List the organization's users")
async def list_users(
    org: Org,
    session: Session,
    filter: str | None = None,
    startIndex: int = 1,  # noqa: N803  SCIM's names
    count: int = 100,
) -> JSONResponse:
    query = select(User).where(User.org_id == org.id)
    if (email := equals_filter(filter, "userName")) is not None:
        query = query.where(User.email == email.lower())
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    users = await session.scalars(
        query.order_by(User.email).offset(max(startIndex, 1) - 1).limit(count)
    )
    return listing([user_resource(u) for u in users], total or 0, startIndex)


@router.post("/Users", summary="Add a user")
async def create_user(org: Org, session: Session, request: Request) -> JSONResponse:
    body = await body_of(request)
    user = User(org_id=org.id, name="", email="")
    apply_user(user, body)
    # Unique in the organization, and among the users outside the sandboxes,
    # whom a sign-in by email finds.
    taken = await session.scalar(
        select(User).where(
            User.email == user.email,
            or_(User.org_id == org.id, outside_sandboxes()),
        )
    )
    if taken is not None:
        raise ScimError(409, f"{user.email} exists", "uniqueness")
    session.add(user)
    record(session, user, "created")
    await set_active(session, user, body.get("active", True) is not False)
    await session.flush()
    await assign_role(session, user)
    await session.commit()
    return scim(user_resource(user), 201)


@router.get("/Users/{id}", summary="Show a user")
async def get_user(id: str, org: Org, session: Session) -> JSONResponse:
    return scim(user_resource(await own_user(session, org, id)))


@router.put("/Users/{id}", summary="Replace a user")
async def replace_user(
    id: str, org: Org, session: Session, request: Request
) -> JSONResponse:
    user = await own_user(session, org, id)
    body = await body_of(request)
    apply_user(user, body)
    await set_active(session, user, body.get("active", True) is not False)
    await session.commit()
    return scim(user_resource(user))


@router.patch("/Users/{id}", summary="Change a user, such as deactivate them")
async def patch_user(
    id: str, org: Org, session: Session, request: Request
) -> JSONResponse:
    user = await own_user(session, org, id)
    for op in (await body_of(request)).get("Operations", []):
        path = (op.get("path") or "").lower()
        value = op.get("value")
        # Okta sends {"value": {"active": false}}, Entra ID {"path": "active"}.
        changes = value if isinstance(value, dict) and not path else {path: value}
        for key, change in changes.items():
            if key.lower() == "active":
                active = change if isinstance(change, bool) else str(change) == "True"
                await set_active(session, user, active)
            elif key.lower() in ("username", "displayname", "externalid"):
                apply_user(user, {**user_resource(user), key: change})
    await session.commit()
    return scim(user_resource(user))


@router.delete("/Users/{id}", status_code=204, summary="Remove a user")
async def delete_user(id: str, org: Org, session: Session) -> Response:
    # Kept, deactivated, as the audit log refers to the user.
    await deactivate(session, await own_user(session, org, id))
    await session.commit()
    return Response(status_code=204)


# Groups


def group_resource(group: DirectoryGroup) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "schemas": [GROUP],
        "id": str(group.id),
        "displayName": group.display_name,
        "members": [{"value": str(u.id), "display": u.email} for u in group.members],
        "meta": {"resourceType": "Group", "location": f"/scim/v2/Groups/{group.id}"},
    }
    if group.external_id:
        resource["externalId"] = group.external_id
    return resource


async def own_group(
    session: AsyncSession, org: Organization, id: str
) -> DirectoryGroup:
    try:
        group = await session.get(DirectoryGroup, uuid.UUID(id))
    except ValueError:
        group = None
    if group is None or group.org_id != org.id:
        raise ScimError(404, f"No group {id}")
    return group


async def members_of(
    session: AsyncSession, org: Organization, values: list[dict[str, Any]]
) -> list[User]:
    return [await own_user(session, org, str(m.get("value"))) for m in values]


async def set_members(
    session: AsyncSession, group: DirectoryGroup, members: list[User]
) -> None:
    """Changes the group's members, and the role of everyone whose groups
    changed."""
    changed = {u.id: u for u in [*group.members, *members]}
    old = {u.id for u in group.members}
    group.members = list({u.id: u for u in members}.values())
    new = {u.id for u in group.members}
    for user in changed.values():
        if (user.id in new) != (user.id in old):
            kind = "joined" if user.id in new else "left"
            record(session, user, kind, group=group.display_name)
    await session.flush()
    for user in changed.values():
        await assign_role(session, user)


@router.get("/Groups", summary="List the organization's groups")
async def list_groups(
    org: Org,
    session: Session,
    filter: str | None = None,
    startIndex: int = 1,  # noqa: N803  SCIM's names
    count: int = 100,
) -> JSONResponse:
    query = select(DirectoryGroup).where(DirectoryGroup.org_id == org.id)
    if (name := equals_filter(filter, "displayName")) is not None:
        query = query.where(DirectoryGroup.display_name == name)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    groups = await session.scalars(
        query.order_by(DirectoryGroup.display_name)
        .offset(max(startIndex, 1) - 1)
        .limit(count)
    )
    return listing([group_resource(g) for g in groups], total or 0, startIndex)


@router.post("/Groups", summary="Add a group")
async def create_group(org: Org, session: Session, request: Request) -> JSONResponse:
    body = await body_of(request)
    name = str(body.get("displayName") or "").strip()
    if not name:
        raise ScimError(400, "displayName is required", "invalidValue")
    taken = await session.scalar(
        select(DirectoryGroup).where(
            DirectoryGroup.org_id == org.id, DirectoryGroup.display_name == name
        )
    )
    if taken is not None:
        raise ScimError(409, f"{name} exists", "uniqueness")
    group = DirectoryGroup(
        org_id=org.id, display_name=name, external_id=body.get("externalId"), members=[]
    )
    session.add(group)
    await set_members(
        session, group, await members_of(session, org, body.get("members") or [])
    )
    await session.commit()
    return scim(group_resource(group), 201)


@router.get("/Groups/{id}", summary="Show a group")
async def get_group(id: str, org: Org, session: Session) -> JSONResponse:
    return scim(group_resource(await own_group(session, org, id)))


@router.put("/Groups/{id}", summary="Replace a group")
async def replace_group(
    id: str, org: Org, session: Session, request: Request
) -> JSONResponse:
    group = await own_group(session, org, id)
    body = await body_of(request)
    group.display_name = str(body.get("displayName") or group.display_name)
    await set_members(
        session, group, await members_of(session, org, body.get("members") or [])
    )
    await session.commit()
    return scim(group_resource(group))


MEMBER_PATH = re.compile(r'members\[value eq "([^"]+)"\]', re.IGNORECASE)


@router.patch("/Groups/{id}", summary="Change a group's name or members")
async def patch_group(
    id: str, org: Org, session: Session, request: Request
) -> JSONResponse:
    group = await own_group(session, org, id)
    members = list(group.members)
    renamed = False
    for op in (await body_of(request)).get("Operations", []):
        kind = (op.get("op") or "").lower()
        path = op.get("path") or ""
        value = op.get("value")
        if path.lower() == "displayname" or (
            not path and isinstance(value, dict) and "displayName" in value
        ):
            group.display_name = (
                value if isinstance(value, str) else value["displayName"]
            )
            renamed = True
        elif kind == "remove" and (found := MEMBER_PATH.fullmatch(path)):
            members = [u for u in members if str(u.id) != found.group(1)]
        elif kind == "remove" and path.lower() == "members":
            gone = {str(m.get("value")) for m in value or []} if value else None
            members = [u for u in members if gone is not None and str(u.id) not in gone]
        elif path.lower() == "members" or (not path and isinstance(value, list)):
            added = await members_of(session, org, value or [])
            members = added if kind == "replace" else [*members, *added]
    await set_members(session, group, members)
    if renamed:
        # A new name may match another rule.
        for user in group.members:
            await assign_role(session, user)
    await session.commit()
    return scim(group_resource(group))


@router.delete("/Groups/{id}", status_code=204, summary="Remove a group")
async def delete_group(id: str, org: Org, session: Session) -> Response:
    group = await own_group(session, org, id)
    await set_members(session, group, [])
    await session.delete(group)
    await session.commit()
    return Response(status_code=204)


# Discovery, which IdPs read before they provision.


@router.get("/ServiceProviderConfig", summary="What this SCIM server supports")
async def service_provider_config() -> JSONResponse:
    off = {"supported": False}
    return scim(
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True},
            "bulk": {**off, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 100},
            "changePassword": off,
            "sort": off,
            "etag": off,
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "Bearer token",
                    "description": "The organization's SCIM token, from its IdP tab.",
                }
            ],
        }
    )


@router.get("/ResourceTypes", summary="The resource types: User and Group")
async def resource_types() -> JSONResponse:
    types = [
        {"id": "User", "name": "User", "endpoint": "/Users", "schema": USER},
        {"id": "Group", "name": "Group", "endpoint": "/Groups", "schema": GROUP},
    ]
    resources = [
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], **t}
        for t in types
    ]
    return listing(resources, len(resources), 1)
