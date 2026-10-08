import json
import os
import shutil
import subprocess

import ollama
from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .tools import ToolError, parse_pdf, scrape_url
from .models import MAX_MESSAGES, Message

SYSTEM_PROMPT = {"role": "system", "content": "You are a helpful, concise assistant."}


def dashboard(request):
    return render(request, "chat/dashboard.html", {"model": settings.OLLAMA_MODEL})


@require_POST
def chat_api(request):
    try:
        payload = json.loads(request.body)
        messages = payload["messages"]
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest('Expected JSON: {"messages": [...]}')

    # Only user/assistant turns are accepted from the browser; the system prompt stays server-side.
    context = payload.get("context")
    history = [SYSTEM_PROMPT] + [
        {"role": m["role"], "content": str(m["content"])}
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and "content" in m
    ]

    if isinstance(context, str) and context.strip() and history[-1]["role"] == "user":
        # Attached document/page text goes to the model only; the saved history keeps the plain question
        question = history[-1]["content"]
        history[-1] = {
            "role": "user",
            "content": f"Use this reference material to answer.\n\n<reference>\n{context[:25000]}\n</reference>\n\n{question}",
        }
        stored = question
    else:
        stored = history[-1]["content"]
    if history[-1]["role"] == "user":
        Message.add("user", stored)

    def token_stream():
        parts = []
        try:
            for chunk in ollama.chat(model=settings.OLLAMA_MODEL, messages=history, stream=True):
                parts.append(chunk["message"]["content"])
                yield parts[-1]
        except Exception as exc:
            yield f"\n[Error talking to Ollama: {exc}]"
        finally:
            if parts:
                Message.add("assistant", "".join(parts))

    response = StreamingHttpResponse(token_stream(), content_type="text/plain; charset=utf-8")
    response["X-Accel-Buffering"] = "no"
    return response


def _meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, val = line.split(":")
            info[key] = int(val.split()[0]) * 1024
    total, avail = info["MemTotal"], info["MemAvailable"]
    return {"total": total, "used": total - avail}


def _gpus():
    if not shutil.which("nvidia-smi"):
        return []
    fields = "name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,power.limit"
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None

    gpus = []
    for line in out.strip().splitlines():
        name, mem_total, mem_used, util, temp, power, power_limit = [x.strip() for x in line.split(",")]
        gpus.append({
            "name": name,
            "mem_total": num(mem_total) * 1024 ** 2,
            "mem_used": num(mem_used) * 1024 ** 2,
            "util": num(util),
            "temp": num(temp),
            "power": num(power),
            "power_limit": num(power_limit),
        })
    return gpus


def stats_api(request):
    cores = os.cpu_count() or 1
    disk = shutil.disk_usage("/")
    return JsonResponse({
        "cpu": {"load": os.getloadavg(), "cores": cores},
        "memory": _meminfo(),
        "disk": {"total": disk.total, "used": disk.used},
        "gpus": _gpus(),
    })


def history_api(request):
    messages = Message.objects.order_by("-id")[:MAX_MESSAGES]
    return JsonResponse({"messages": [{"role": m.role, "content": m.content, "ts": m.created_at.isoformat()} for m in reversed(messages)]})


@require_POST
def scrape_api(request):
    try:
        url = json.loads(request.body)["url"].strip()
        return JsonResponse(scrape_url(url))
    except (ValueError, KeyError, TypeError, AttributeError):
        return JsonResponse({"error": 'Expected JSON: {"url": "..."}'}, status=400)
    except ToolError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
def pdf_api(request):
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "Upload a PDF as form field 'file'."}, status=400)
    try:
        return JsonResponse(parse_pdf(file))
    except ToolError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
