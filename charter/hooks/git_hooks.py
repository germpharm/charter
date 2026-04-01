"""Git hooks for Charter — auto-hash every commit and merge.

Installs post-commit and post-merge hooks that call append_to_chain()
with commit metadata. The hooks are shell scripts that invoke
`charter log` with the appropriate event type.

Usage:
    charter hooks install          # Install git hooks in current repo
    charter hooks install --global # Install as global git hooks
    charter hooks status           # Show which hooks are installed
    charter hooks uninstall        # Remove Charter git hooks
"""

import os
import stat
import subprocess


# Template for the post-commit hook
POST_COMMIT_HOOK = '''#!/bin/sh
# Charter v3.1.1 — Always-On Hash Chain
# This hook fires after every git commit and records it to the Charter chain.
# Do not edit — managed by `charter hooks install`.

# Get commit metadata
COMMIT_HASH=$(git rev-parse HEAD)
COMMIT_MSG=$(git log -1 --pretty=format:"%s" HEAD)
COMMIT_AUTHOR=$(git log -1 --pretty=format:"%an <%ae>" HEAD)
FILES_CHANGED=$(git diff-tree --no-commit-id --name-only -r HEAD | tr '\\n' ', ' | sed 's/,$//')
INSERTIONS=$(git diff --stat HEAD~1 HEAD 2>/dev/null | tail -1 | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || echo "0")
DELETIONS=$(git diff --stat HEAD~1 HEAD 2>/dev/null | tail -1 | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' || echo "0")

# Log to Charter chain
charter log code_committed \\
    --actor human \\
    --data-json "{\\
\\"commit_hash\\": \\"$COMMIT_HASH\\",\\
\\"message\\": \\"$COMMIT_MSG\\",\\
\\"author\\": \\"$COMMIT_AUTHOR\\",\\
\\"files_changed\\": \\"$FILES_CHANGED\\",\\
\\"insertions\\": $INSERTIONS,\\
\\"deletions\\": $DELETIONS\\
}" 2>/dev/null || true
'''

# Template for the post-merge hook
POST_MERGE_HOOK = '''#!/bin/sh
# Charter v3.1.1 — Always-On Hash Chain
# This hook fires after every git merge and records it to the Charter chain.

MERGE_HASH=$(git rev-parse HEAD)
MERGE_MSG=$(git log -1 --pretty=format:"%s" HEAD)
MERGE_AUTHOR=$(git log -1 --pretty=format:"%an <%ae>" HEAD)

charter log branch_merged \\
    --actor human \\
    --data-json "{\\
\\"merge_hash\\": \\"$MERGE_HASH\\",\\
\\"message\\": \\"$MERGE_MSG\\",\\
\\"author\\": \\"$MERGE_AUTHOR\\"\\
}" 2>/dev/null || true
'''

CHARTER_MARKER = "# Charter v3.1.1"


def get_git_hooks_dir(path=None):
    """Get the .git/hooks directory for a repository.

    Args:
        path: Repository path (default: current directory)

    Returns:
        str: Path to hooks directory, or None if not a git repo
    """
    try:
        cwd = path or os.getcwd()
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=cwd,
        )
        if result.returncode != 0:
            return None
        git_dir = result.stdout.strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(cwd, git_dir)
        return os.path.join(git_dir, "hooks")
    except Exception:
        return None


def get_global_hooks_dir():
    """Get or create the global git hooks directory."""
    result = subprocess.run(
        ["git", "config", "--global", "core.hooksPath"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    # Default location
    hooks_dir = os.path.expanduser("~/.charter/git-hooks")
    return hooks_dir


def install_hook(hooks_dir, hook_name, hook_content):
    """Install a single git hook, preserving existing hooks.

    If a hook already exists and is not a Charter hook, the Charter
    hook is appended to the existing script.
    """
    os.makedirs(hooks_dir, exist_ok=True)
    hook_path = os.path.join(hooks_dir, hook_name)

    if os.path.isfile(hook_path):
        with open(hook_path) as f:
            existing = f.read()

        if CHARTER_MARKER in existing:
            # Already installed — update in place
            # Find the Charter section and replace it
            lines = existing.split("\n")
            new_lines = []
            in_charter = False
            for line in lines:
                if CHARTER_MARKER in line:
                    in_charter = True
                    continue
                if in_charter and line.startswith("# End Charter"):
                    in_charter = False
                    continue
                if not in_charter:
                    new_lines.append(line)

            # Append new Charter section
            charter_section = f"\n{hook_content.split('#!/bin/sh')[1] if '#!/bin/sh' in hook_content else hook_content}\n# End Charter hook\n"
            with open(hook_path, "w") as f:
                f.write("\n".join(new_lines) + charter_section)
        else:
            # Existing non-Charter hook — append
            with open(hook_path, "a") as f:
                f.write(f"\n\n{CHARTER_MARKER}\n")
                # Strip shebang from appended content
                content = hook_content.split("\n", 1)[1] if hook_content.startswith("#!") else hook_content
                f.write(content)
                f.write("\n# End Charter hook\n")
    else:
        with open(hook_path, "w") as f:
            f.write(hook_content)

    # Make executable
    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return hook_path


def install_hooks(path=None, global_hooks=False):
    """Install Charter git hooks.

    Args:
        path: Repository path (for local install)
        global_hooks: If True, install as global git hooks

    Returns:
        dict: {"installed": list of hook paths, "errors": list}
    """
    if global_hooks:
        hooks_dir = get_global_hooks_dir()
        os.makedirs(hooks_dir, exist_ok=True)
        # Set global hooks path
        subprocess.run(
            ["git", "config", "--global", "core.hooksPath", hooks_dir],
            capture_output=True,
        )
    else:
        hooks_dir = get_git_hooks_dir(path)
        if not hooks_dir:
            return {"installed": [], "errors": ["Not a git repository"]}

    installed = []
    errors = []

    for hook_name, hook_content in [
        ("post-commit", POST_COMMIT_HOOK),
        ("post-merge", POST_MERGE_HOOK),
    ]:
        try:
            result = install_hook(hooks_dir, hook_name, hook_content)
            installed.append(result)
        except Exception as e:
            errors.append(f"{hook_name}: {e}")

    return {"installed": installed, "errors": errors}


def uninstall_hooks(path=None, global_hooks=False):
    """Remove Charter git hooks.

    Removes only the Charter sections — preserves other hooks.
    """
    if global_hooks:
        hooks_dir = get_global_hooks_dir()
    else:
        hooks_dir = get_git_hooks_dir(path)
        if not hooks_dir:
            return {"removed": [], "errors": ["Not a git repository"]}

    removed = []
    errors = []

    for hook_name in ("post-commit", "post-merge"):
        hook_path = os.path.join(hooks_dir, hook_name)
        if not os.path.isfile(hook_path):
            continue

        try:
            with open(hook_path) as f:
                content = f.read()

            if CHARTER_MARKER not in content:
                continue

            # Remove Charter sections
            lines = content.split("\n")
            new_lines = []
            in_charter = False
            for line in lines:
                if CHARTER_MARKER in line:
                    in_charter = True
                    continue
                if in_charter and "# End Charter" in line:
                    in_charter = False
                    continue
                if not in_charter:
                    new_lines.append(line)

            cleaned = "\n".join(new_lines).strip()
            if cleaned and cleaned != "#!/bin/sh":
                with open(hook_path, "w") as f:
                    f.write(cleaned + "\n")
            else:
                os.remove(hook_path)

            removed.append(hook_path)
        except Exception as e:
            errors.append(f"{hook_name}: {e}")

    return {"removed": removed, "errors": errors}


def hooks_status(path=None, global_hooks=False):
    """Check which Charter hooks are installed.

    Returns:
        dict: hook_name -> {"installed": bool, "path": str}
    """
    if global_hooks:
        hooks_dir = get_global_hooks_dir()
    else:
        hooks_dir = get_git_hooks_dir(path)
        if not hooks_dir:
            return {}

    status = {}
    for hook_name in ("post-commit", "post-merge"):
        hook_path = os.path.join(hooks_dir, hook_name)
        installed = False
        if os.path.isfile(hook_path):
            with open(hook_path) as f:
                installed = CHARTER_MARKER in f.read()
        status[hook_name] = {"installed": installed, "path": hook_path}

    return status


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_hooks(args):
    """CLI entry point for charter hooks."""
    action = getattr(args, "action", "status")
    is_global = getattr(args, "global_hooks", False)

    if action == "install":
        result = install_hooks(global_hooks=is_global)
        if result["installed"]:
            scope = "global" if is_global else "local"
            print(f"Charter git hooks installed ({scope}):")
            for path in result["installed"]:
                print(f"  {path}")
            print()
            print("Every git commit and merge will now be recorded to the Charter chain.")
        if result["errors"]:
            for err in result["errors"]:
                print(f"  Error: {err}")

    elif action == "uninstall":
        result = uninstall_hooks(global_hooks=is_global)
        if result["removed"]:
            print("Charter git hooks removed:")
            for path in result["removed"]:
                print(f"  {path}")
        else:
            print("No Charter hooks found to remove.")
        if result["errors"]:
            for err in result["errors"]:
                print(f"  Error: {err}")

    elif action == "status":
        status = hooks_status(global_hooks=is_global)
        if not status:
            print("Not in a git repository (use --global for global hooks).")
            return

        print("Charter Git Hooks Status:")
        for hook_name, info in status.items():
            state = "INSTALLED" if info["installed"] else "not installed"
            print(f"  {hook_name}: {state}")
            print(f"    Path: {info['path']}")

    else:
        print(f"Unknown hooks action: {action}")
        print("Valid actions: install, uninstall, status")
