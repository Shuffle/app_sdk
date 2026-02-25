"""
Sandbox - Spawn isolated subprocess for code execution.

HOW IT WORKS:
1. Caller provides code + type (python/bash/liquid)
2. We spawn sandbox_worker.py as a subprocess
3. Send code as JSON via stdin
4. Read result as JSON from stdout
5. Return result to caller

ISOLATION PROVIDED:
- Fresh Python interpreter (no shared state between executions)
- Resource limits applied in worker (memory, CPU, files)
- Clean environment (no inherited secrets)
- Timeout enforcement
- Output size limits

USAGE:
    from shuffle_sdk.sandbox import run_python, run_bash

    result = run_python("print(1 + 1)")
    # {"success": True, "result": "2"}

    result = run_bash("echo hello")
    # {"success": True, "result": "hello"}
"""

import os
import sys
import json
import subprocess


# =============================================================================
# CONFIGURATION
# =============================================================================

# Path to the worker script (same directory as this file)
WORKER_PATH = os.path.join(os.path.dirname(__file__), "sandbox_worker.py")

# SANDBOX MODE: Defaults to True (sandboxed execution enabled)
# Set to False to disable sandboxing and run code directly (NOT RECOMMENDED)
# You must explicitly set this to False to disable sandboxing
SANDBOX_ENABLED = True

# Limits
# Use SHUFFLE_APP_SDK_TIMEOUT env var if available, otherwise 60 seconds
# But set to 55 seconds (5 less) to give worker time before parent timeout
_env_timeout = os.getenv("SHUFFLE_APP_SDK_TIMEOUT")
TIMEOUT_SECONDS = int(_env_timeout) - 5 if _env_timeout else 55
MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10MB

# Print to stderr at module load time to ensure visibility
_msg = "=" * 80
print(_msg, file=sys.stderr, flush=True)
print("[SANDBOX] SANDBOX MODE ENABLED BY DEFAULT", file=sys.stderr, flush=True)
print("[SANDBOX] All code execution is isolated in subprocesses", file=sys.stderr, flush=True)
print("[SANDBOX] To disable, set sandbox.SANDBOX_ENABLED = False (not recommended)", file=sys.stderr, flush=True)
print(_msg, file=sys.stderr, flush=True)


# =============================================================================
# CONTEXT HELPERS
# =============================================================================

def _extract_sdk_context(sdk_instance):
    """
    Extract serializable context from SDK instance.
    Instead of pickling, we extract key data and send as JSON.
    Worker can reconstruct or use directly.
    Returns None if extraction fails.
    """
    if not sdk_instance:
        return None
    try:
        context = {
            "url": getattr(sdk_instance, "url", ""),
            "base_url": getattr(sdk_instance, "base_url", ""),
            "authorization": getattr(sdk_instance, "authorization", ""),
            "current_execution_id": getattr(sdk_instance, "current_execution_id", ""),
            "full_execution": getattr(sdk_instance, "full_execution", {}),
            "action": getattr(sdk_instance, "action", {}),
            "original_action": getattr(sdk_instance, "original_action", {}),
            "start_time": getattr(sdk_instance, "start_time", 0),
            "proxy_config": getattr(sdk_instance, "proxy_config", {}),
            "local_storage": getattr(sdk_instance, "local_storage", []),
        }

        # Try to include singul reference if available
        try:
            if hasattr(sdk_instance, "singul") and sdk_instance.singul:
                context["has_singul"] = True
        except:
            pass

        return context
    except Exception as e:
        print(f"[SANDBOX] Failed to extract SDK context: {e}", file=sys.stderr, flush=True)
        return None


# =============================================================================
# CORE EXECUTION
# =============================================================================

def _run_worker(exec_type, code, sdk_instance=None, extra_context=None):
    """
    Spawn worker subprocess and execute code.

    Args:
        exec_type: "python", "bash", or "liquid"
        code: Code/command/template to execute
        sdk_instance: Optional SDK instance (will be pickled)
        extra_context: Optional extra dict to merge into context

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}
    """
    if not SANDBOX_ENABLED:
        print("[SANDBOX] WARNING: SANDBOXING IS DISABLED! This is unsafe.", file=sys.stderr, flush=True)
        print("[SANDBOX] Code is running in the main process without isolation.", file=sys.stderr, flush=True)
        print("[SANDBOX] To re-enable, set: sandbox.SANDBOX_ENABLED = True", file=sys.stderr, flush=True)
    # Build request with SDK context (extracted data instead of pickle)
    sdk_context = _extract_sdk_context(sdk_instance)
    request = {
        "type": exec_type,
        "code": code,
        "sdk_context": sdk_context,
        "extra_context": extra_context or {},
    }
    request_json = json.dumps(request)

    # Clean environment for worker
    # Put the app directory (parent of shuffle_sdk/) first in PYTHONPATH
    # so the local shuffle_sdk package is found before the system-level one
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_path = app_dir + ":" + ":".join(sys.path)

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "PYTHONPATH": python_path,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }

    code_preview = code[:200] if len(code) > 200 else code
    msg1 = f"[SANDBOX] Starting {exec_type} execution in subprocess"
    msg2 = f"[SANDBOX] Type: {exec_type}"
    msg3 = f"[SANDBOX] Code: {repr(code_preview)}{'...' if len(code) > 200 else ''}"
    msg4 = f"[SANDBOX] Has SDK context: {sdk_instance is not None}"

    for msg in [msg1, msg2, msg3, msg4]:
        print(msg, file=sys.stderr, flush=True)

    try:
        # Spawn worker
        msg = f"[SANDBOX] Spawning worker subprocess with worker script: {WORKER_PATH}"
        print(msg, file=sys.stderr, flush=True)

        proc = subprocess.Popen(
            [sys.executable, WORKER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd="/tmp",
            start_new_session=True,  # Own process group for clean termination
        )

        msg = f"[SANDBOX] Worker process spawned (PID: {proc.pid})"
        print(msg, file=sys.stderr, flush=True)

        # Send request, wait for response
        try:
            msg = f"[SANDBOX] Sending request to worker, timeout={TIMEOUT_SECONDS}s"
            print(msg, file=sys.stderr, flush=True)

            stdout, stderr = proc.communicate(
                input=request_json.encode("utf-8"),
                timeout=TIMEOUT_SECONDS,
            )

            msg = f"[SANDBOX] Worker completed with return code: {proc.returncode}"
            print(msg, file=sys.stderr, flush=True)
            print(f"[SANDBOX] stdout length: {len(stdout)} bytes", file=sys.stderr, flush=True)
            print(f"[SANDBOX] stderr length: {len(stderr)} bytes", file=sys.stderr, flush=True)
            if stdout:
                stdout_text = stdout.decode('utf-8', errors='replace')
                print(f"[SANDBOX] stdout (JSON result): {stdout_text[:300]}", file=sys.stderr, flush=True)
            if stderr:
                stderr_text = stderr.decode('utf-8', errors='replace')
                print(f"[SANDBOX] stderr (worker logs): {stderr_text[:200]}", file=sys.stderr, flush=True)
        except subprocess.TimeoutExpired:
            msg = f"[SANDBOX] Timeout! Killing process group after {TIMEOUT_SECONDS}s"
            print(msg, file=sys.stderr, flush=True)
            # Kill the entire process group
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except:
                proc.kill()
            proc.wait()
            return {"success": False, "error": f"Execution timed out after {TIMEOUT_SECONDS} seconds"}

        # Limit output size
        if len(stdout) > MAX_OUTPUT_BYTES:
            msg = f"[SANDBOX] Output truncated from {len(stdout)} to {MAX_OUTPUT_BYTES} bytes"
            print(msg, file=sys.stderr, flush=True)
            stdout = stdout[:MAX_OUTPUT_BYTES]

        # Parse result
        if proc.returncode == 0 and stdout:
            try:
                result = json.loads(stdout.decode("utf-8"))
                msg = f"[SANDBOX] Successfully parsed JSON result"
                print(msg, file=sys.stderr, flush=True)
                return result
            except json.JSONDecodeError:
                result_text = stdout.decode("utf-8", errors="replace")
                msg = f"[SANDBOX] Output is not JSON, returning as text"
                print(msg, file=sys.stderr, flush=True)
                return {"success": True, "result": result_text}
        else:
            error_msg = stderr.decode("utf-8", errors="replace") if stderr else f"Exit code {proc.returncode}"
            msg = f"[SANDBOX] Execution failed: {error_msg}"
            print(msg, file=sys.stderr, flush=True)
            return {"success": False, "error": error_msg}

    except FileNotFoundError:
        msg = f"[SANDBOX] Worker script not found: {WORKER_PATH}"
        print(msg, file=sys.stderr, flush=True)
        return {"success": False, "error": f"Worker script not found: {WORKER_PATH}"}
    except Exception as e:
        msg = f"[SANDBOX] Unexpected error during execution: {e}"
        print(msg, file=sys.stderr, flush=True)
        return {"success": False, "error": f"Sandbox error: {e}"}


# =============================================================================
# PUBLIC API
# =============================================================================

def run_python(code, sdk_instance=None):
    """
    Execute Python code in isolated subprocess.

    Args:
        code: Python source code to execute
        sdk_instance: Optional AppBase instance (pickled and available as 'self')

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}

    Example:
        result = run_python("print(2 + 2)")
        # {"success": True, "result": "4"}
    """
    return _run_worker("python", code, sdk_instance)


def run_bash(code, sdk_instance=None, shuffle_input=None):
    """
    Execute bash command in isolated subprocess.

    Args:
        code: Bash command to execute
        sdk_instance: Optional AppBase instance (pickled)
        shuffle_input: Optional string available as $SHUFFLE_INPUT

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}

    Example:
        result = run_bash("echo hello world")
        # {"success": True, "result": "hello world"}
    """
    extra = {"shuffle_input": shuffle_input} if shuffle_input else None
    return _run_worker("bash", code, sdk_instance, extra)


def run_liquid(template, sdk_instance=None):
    """
    Render Liquid template in isolated subprocess.

    Args:
        template: Liquid template string
        sdk_instance: Optional AppBase instance (pickled)

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}

    Example:
        result = run_liquid("Hello {{ name }}")
        # {"success": True, "result": "Hello ..."}
    """
    # Extract action parameters from SDK instance to make them available in liquid template
    extra_context = {}
    if sdk_instance:
        try:
            # Get action parameters if they exist
            if hasattr(sdk_instance, 'action') and isinstance(sdk_instance.action, dict):
                # Add each parameter to context by name
                for param in sdk_instance.action.get('parameters', []):
                    param_name = param.get('name', '')
                    param_value = param.get('value', '')
                    if param_name:
                        extra_context[param_name] = param_value

            # Also add env dict if it exists (for backward compatibility)
            if hasattr(sdk_instance, 'env') and isinstance(sdk_instance.env, dict):
                extra_context.update(sdk_instance.env)
        except:
            pass  # Ignore errors extracting context

    return _run_worker("liquid", template, sdk_instance, extra_context if extra_context else None)


def is_available():
    """Check if sandbox worker exists."""
    return os.path.exists(WORKER_PATH)


def configure(timeout_seconds=None, max_output_bytes=None):
    """
    Update sandbox configuration.

    Args:
        timeout_seconds: Max execution time (default 60)
        max_output_bytes: Max output size (default 10MB)
    """
    global TIMEOUT_SECONDS, MAX_OUTPUT_BYTES
    if timeout_seconds is not None:
        TIMEOUT_SECONDS = timeout_seconds
    if max_output_bytes is not None:
        MAX_OUTPUT_BYTES = max_output_bytes
