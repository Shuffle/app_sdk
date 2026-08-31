#!/usr/bin/env python3
"""
Sandbox Worker - Isolated code execution via stdin/stdout.

HOW IT WORKS:
1. Parent process spawns this worker as a subprocess
2. Worker reads JSON from stdin (contains code + context)
3. Worker applies resource limits (memory, CPU, etc.)
4. Worker executes the code in isolation
5. Worker writes JSON result to stdout

ISOLATION PROVIDED:
- Fresh Python interpreter per execution (no shared state)
- Resource limits prevent runaway processes
- Clean environment (no inherited secrets)
- Runs as separate process (can't access parent memory)

USAGE:
    echo '{"type": "python", "code": "print(1+1)"}' | python sandbox_worker.py
"""

import sys
import json
import resource
import subprocess
from io import StringIO


# =============================================================================
# LOGGING
# =============================================================================

def log_stderr(msg):
    """Log message to stderr with worker prefix"""
    print(f"[EXECUTE_WORKER] {msg}", file=sys.stderr, flush=True)


# =============================================================================
# RESOURCE LIMITS
# =============================================================================

def apply_limits():
    """
    Apply resource limits immediately when worker starts.

    These limits prevent:
    - Memory exhaustion (512MB max)
    - CPU hogging (60 seconds max)
    - Disk filling (50MB max file size)
    - File descriptor exhaustion (100 max open files)
    - Core dumps (disabled)
    """
    import platform

    # Memory: 512MB max
    try:
        mem_bytes = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, resource.error):
        pass  # Some systems don't support this

    # CPU: 60 seconds max
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    except (ValueError, resource.error):
        pass

    # File size: 50MB max per file
    try:
        file_bytes = 50 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    except (ValueError, resource.error):
        pass

    # Open files: 100 max
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (100, 100))
    except (ValueError, resource.error):
        pass

    # Process limit: 50 max (Linux only - causes issues on macOS)
    if platform.system() == "Linux":
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
        except (ValueError, resource.error):
            pass

    # No core dumps
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, resource.error):
        pass


# Apply limits immediately when worker starts
apply_limits()


# =============================================================================
# HELPERS
# =============================================================================

def _reconstruct_sdk(sdk_context):
    """
    Reconstruct a minimal SDK object from context data.
    This gives us access to sdk attributes without needing pickle.
    Returns a simple object with the context attributes, or None if context is empty.
    """
    if not sdk_context:
        return None

    try:
        # Create a simple object to hold the context attributes
        class SDKContextHolder:
            pass

        sdk = SDKContextHolder()

        # Apply all context attributes
        for key, value in sdk_context.items():
            setattr(sdk, key, value)

        # Try to initialize singul if the context indicates it exists
        if sdk_context.get("has_singul"):
            try:
                # Try to create a fresh singul object
                # This assumes the environment variables are set properly
                from shuffle_sdk import AppBase
                temp_app = AppBase()
                sdk.singul = temp_app.singul
            except:
                # If we can't initialize singul, at least the context is there
                pass

        return sdk
    except Exception as e:
        return None


# =============================================================================
# EXECUTION FUNCTIONS
# =============================================================================

def execute_python(code, sdk, context):
    """
    Execute Python code and capture output.

    Args:
        code: Python source code to execute
        sdk: SDK instance (available as 'self')
        context: Extra context dict

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}
    """
    try:
        # Capture print() output
        output = StringIO()

        def captured_print(*args, **kwargs):
            kwargs["file"] = output
            print(*args, **kwargs)

        # Build execution environment (mirrors what app.py provides)
        exec_env = globals().copy()
        exec_env["print"] = captured_print
        exec_env["self"] = sdk

        # singul/shuffle point to the Singul API object (same as app.py)
        if sdk:
            try:
                exec_env["singul"] = sdk.singul
                exec_env["shuffle"] = sdk.singul
            except:
                pass

        # Execute the code with comprehensive error handling
        try:
            exec(code, exec_env)
        except SystemExit:
            pass  # Allow exit() without crashing
        except SyntaxError as e:
            if "'return' outside function" in str(e):
                return {"success": False, "error": "Use exit() instead of return at top level", "error_type": "SyntaxError"}
            return {"success": False, "error": f"SyntaxError: {e}", "error_type": "SyntaxError"}
        except IndentationError as e:
            return {"success": False, "error": f"IndentationError: {e}", "error_type": "IndentationError"}
        except TypeError as e:
            return {"success": False, "error": f"TypeError: {e}", "error_type": "TypeError"}
        except NameError as e:
            return {"success": False, "error": f"NameError: {e}", "error_type": "NameError"}
        except ValueError as e:
            return {"success": False, "error": f"ValueError: {e}", "error_type": "ValueError"}
        except Exception as e:
            import traceback
            etype = type(e).__name__
            # Log full traceback to stderr for debugging
            print(f"[EXECUTE_PYTHON] UNEXPECTED ERROR: {etype}: {e}", file=sys.stderr, flush=True)
            print(f"[EXECUTE_PYTHON] Traceback: {traceback.format_exc()}", file=sys.stderr, flush=True)
            msg = f"There was an error executing your Python code. Type: {etype}. Details: {e}"
            return {"success": False, "error": msg, "error_type": etype}

        # Get output
        result = output.getvalue().strip()

        # Try to parse as JSON (common pattern)
        try:
            return {"success": True, "result": json.loads(result)}
        except (json.JSONDecodeError, ValueError):
            return {"success": True, "result": result}

    except Exception as e:
        import traceback
        print(f"[EXECUTE_PYTHON] OUTER ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        print(f"[EXECUTE_PYTHON] Traceback: {traceback.format_exc()}", file=sys.stderr, flush=True)
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


def execute_bash(code, context):
    """
    Execute bash command and capture output.

    Args:
        code: Bash command to execute
        context: Dict with extra data (shuffle_input available as $SHUFFLE_INPUT)

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ...}
    """
    try:
        # Clean environment - no inherited secrets
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }

        # Add shuffle_input if provided
        shuffle_input = context.get("shuffle_input", "")
        if shuffle_input:
            env["SHUFFLE_INPUT"] = shuffle_input

        # Run the command
        proc = subprocess.Popen(
            code,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd="/tmp",
        )

        stdout, stderr = proc.communicate(timeout=55)

        # Get output (prefer stdout, fall back to stderr)
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output and stderr:
            output = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            return {"success": True, "result": output}
        else:
            return {"success": False, "error": output or f"Exit code {proc.returncode}"}

    except subprocess.TimeoutExpired:
        proc.kill()
        return {"success": False, "error": "Command timed out after 55 seconds"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_liquid(template, sdk, context):
    """
    Render a Liquid template with proper exception handling.

    Returns:
        {"success": True, "result": ...} or {"success": False, "error": ..., "error_type": ...}
    """
    try:
        from liquid import Liquid
        import jinja2

        # Import filters
        try:
            from shuffle_sdk import shuffle_filters
        except ImportError:
            from walkoff_app_sdk import shuffle_filters

        # Build template globals
        template_globals = {}
        if context:
            template_globals.update(context)
        if sdk:
            template_globals["self"] = sdk
            try:
                template_globals["singul"] = sdk.singul
                template_globals["shuffle"] = sdk.singul
            except:
                pass

        # Render - let exceptions bubble up to be caught below
        liq = Liquid(template, mode="wild", from_file=False,
                     filters=shuffle_filters.filters, globals=template_globals)
        result = liq.render()
        return {"success": True, "result": result}

    except jinja2.exceptions.TemplateNotFound as e:
        msg = f"There was a Liquid input error (1). Details: {e}"
        return {"success": False, "error": msg, "error_type": "TemplateNotFound"}
    except SyntaxError as e:
        msg = f"There was a syntax error in your Liquid input (2). Details: {e}"
        return {"success": False, "error": msg, "error_type": "SyntaxError"}
    except IndentationError as e:
        msg = f"There was an indentation error in your Liquid input (2). Details: {e}"
        return {"success": False, "error": msg, "error_type": "IndentationError"}
    except jinja2.exceptions.TemplateSyntaxError as e:
        msg = f"There was a syntax error in your Liquid input (2). Details: {e}"
        return {"success": False, "error": msg, "error_type": "TemplateSyntaxError"}
    except json.JSONDecodeError as e:
        msg = f"There was a syntax error in your input JSON (2). This is typically an issue with escaping newlines. Details: {e}"
        return {"success": False, "error": msg, "error_type": "JSONDecodeError"}
    except TypeError as e:
        msg = f"There was a type error in your Liquid input (2). Details: {e}"
        return {"success": False, "error": msg, "error_type": "TypeError"}
    except Exception as e:
        import traceback
        etype = type(e).__name__
        # Log full traceback to stderr so we can debug
        log_stderr(f"UNEXPECTED ERROR in execute_liquid: {etype}: {e}")
        log_stderr(f"Traceback: {traceback.format_exc()}")
        msg = f"There was a general error in your Liquid input. Type: {etype}. Details: {e}"
        return {"success": False, "error": msg, "error_type": etype}


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """
    Read JSON from stdin, execute requested operation, output JSON result.

    Input format:
        {
            "type": "python" | "bash" | "liquid",
            "code": "...",
            "context": {...}  # Optional SDK state
        }

    Output format:
        {"success": true, "result": ...}
        or
        {"success": false, "error": "..."}
    """
    # Log to stderr so it doesn't interfere with stdout (which is JSON output)
    import sys
    def log_stderr(msg):
        print(f"[SANDBOX_WORKER] {msg}", file=sys.stderr, flush=True)

    # log_stderr("Worker process started")

    try:
        # Read input from stdin
        # log_stderr("Reading request from stdin...")
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"success": False, "error": "No input provided"}))
            sys.exit(1)

        # Parse input
        try:
            request = json.loads(raw_input)
            # log_stderr("Request parsed successfully")
        except json.JSONDecodeError as e:
            # log_stderr(f"Failed to parse JSON: {e}")
            print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
            sys.exit(1)

        # Extract fields
        exec_type = request.get("type", "")
        code = request.get("code", "")
        sdk_context = request.get("sdk_context")  # SDK context data (extracted instead of pickled)
        extra_context = request.get("extra_context", {})  # Extra context data

        # log_stderr(f"Execution type: {exec_type}")
        # log_stderr(f"Code length: {len(code)} bytes")
        # Reconstruct SDK object from context data
        sdk = _reconstruct_sdk(sdk_context)

        # log_stderr(f"Has SDK context: {sdk_context is not None}")

        # Validate
        if not exec_type:
            # log_stderr("ERROR: Missing 'type' field")
            print(json.dumps({"success": False, "error": "Missing 'type' field"}))
            sys.exit(1)
        if not code:
            # log_stderr("ERROR: Missing 'code' field")
            print(json.dumps({"success": False, "error": "Missing 'code' field"}))
            sys.exit(1)

        # Execute with reconstructed SDK
        # log_stderr(f"Starting {exec_type} execution...")
        if exec_type == "python":
            result = execute_python(code, sdk, extra_context)
        elif exec_type == "bash":
            result = execute_bash(code, extra_context)
        elif exec_type == "liquid":
            result = execute_liquid(code, sdk, extra_context)
        else:
            # log_stderr(f"ERROR: Unknown execution type: {exec_type}")
            result = {"success": False, "error": f"Unknown type: {exec_type}"}

        # Output result
        # (debug logging disabled to keep stderr clean)
        print(json.dumps(result))

    except Exception as e:
        import traceback
        # Log full traceback to stderr so we can debug
        print(f"[EXECUTE_WORKER] CRITICAL ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        print(f"[EXECUTE_WORKER] Traceback:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        print(json.dumps({"success": False, "error": f"Worker error: {e}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
