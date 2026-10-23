"""`/mcp`: MCP Streamable HTTP, JSON-response mode only, inside the sync (WSGI) Django app.

Each POST carries one JSON-RPC message and gets one `application/json` answer (202 with no body
for notifications). There is no SSE stream (GET answers 405) and no session (no
`Mcp-Session-Id`), which the transport allows. Every method needs a sandcorp-auth access token
with scope `admin` (`oauth.bearer`).
"""

import json

from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from mcpserver.protocol import INVALID_REQUEST, PARSE_ERROR, PROTOCOL_VERSIONS, dispatch, error
from oauth.bearer import require_bearer
from oauth.tokens import AccessToken

MCP_SCOPE = "admin"


@csrf_exempt  # bearer tokens only, no cookies: CSRF does not apply
@require_bearer(MCP_SCOPE)
def mcp_endpoint(request: HttpRequest, token: AccessToken) -> HttpResponse:
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response
    version = request.headers.get("MCP-Protocol-Version")
    if version is not None and version not in PROTOCOL_VERSIONS:
        return JsonResponse(
            error(None, INVALID_REQUEST, f"unsupported MCP-Protocol-Version: {version}"),
            status=400,
        )
    try:
        message: object = json.loads(request.body)
    except RequestDataTooBig:
        return JsonResponse(error(None, INVALID_REQUEST, "request too large"), status=413)
    except ValueError:
        return JsonResponse(error(None, PARSE_ERROR, "parse error"), status=400)
    if isinstance(message, list):
        return JsonResponse(error(None, INVALID_REQUEST, "batches are not supported"), status=400)
    answer = dispatch(message, token)
    if answer is None:
        return HttpResponse(status=202)
    return JsonResponse(answer, json_dumps_params={"ensure_ascii": False})
