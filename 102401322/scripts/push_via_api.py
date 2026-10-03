"""通过 GitHub 的 Git Data API 把本地提交历史推到远程仓库。

为什么要写这个脚本：这台机器上 github.com 连不上（HTTPS 推送直接连接重置），
但 api.github.com 是通的，`gh` 命令行也是通的。
所以改用 REST API 逐个上传 git 对象，把历史原样重建出来。

用法：
    python scripts/push_via_api.py <owner/repo> [分支名]

注意：这个脚本只在网络受限、git push 不通的时候才需要，正常情况下直接 git push 就行。
"""

import base64
import json
import subprocess
import sys


def run_git(*args):
    """执行 git 命令，返回输出。

    加了 core.quotepath=false，不然 git 会把中文文件名转义成八进制，
    后面按路径读文件就会报错。
    """
    result = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                            capture_output=True)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", "ignore")
        raise RuntimeError("git %s 失败：%s" % (" ".join(args), error))
    return result.stdout.decode("utf-8", "ignore")


def gh_api(endpoint, method="GET", body=None):
    """调用 gh api。endpoint 不能以 / 开头，否则 Git Bash 会把它当成路径改写。"""
    cmd = ["gh", "api", endpoint, "--method", method]
    if body is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(cmd, input=json.dumps(body).encode("utf-8") if body else None,
                            capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("gh api %s 失败：%s" % (endpoint, result.stderr.decode("utf-8", "ignore")))
    text = result.stdout.decode("utf-8", "ignore")
    return json.loads(text) if text.strip() else {}


def get_history(branch):
    """按时间从早到晚拿到所有提交。"""
    output = run_git("rev-list", "--reverse", branch)
    return [line.strip() for line in output.splitlines() if line.strip()]


def commit_info(sha):
    """拿一个提交的元信息（作者、时间、说明）。"""
    raw = run_git("show", "-s", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", sha)
    parts = raw.split("\x00")
    return {
        "author_name": parts[0],
        "author_email": parts[1],
        "author_date": parts[2],
        "committer_name": parts[3],
        "committer_email": parts[4],
        "committer_date": parts[5],
        "message": parts[6].rstrip("\n"),
    }


def changed_files(sha):
    """这个提交改了哪些文件，返回 [(状态, 路径)]，状态是 A/M/D。"""
    if "parents" in run_git("cat-file", "-p", sha):
        output = run_git("diff-tree", "--no-commit-id", "--name-status", "-r", "-M", sha)
    else:
        output = run_git("show", "--name-status", "--format=", "-r", sha)

    files = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]
        path = parts[-1].strip()
        if path:
            files.append((status, path))
    return files


def make_blob(owner_repo, path):
    """把一个文件的内容上传成 blob，返回 sha。"""
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    result = gh_api("repos/%s/git/blobs" % owner_repo, "POST",
                    {"content": content, "encoding": "base64"})
    return result["sha"]


def make_tree(owner_repo, entries, base_tree=None):
    """创建一个 tree。entries 里 sha 为 None 表示删除该文件。"""
    body = {"tree": entries}
    if base_tree:
        body["base_tree"] = base_tree
    return gh_api("repos/%s/git/trees" % owner_repo, "POST", body)["sha"]


def make_commit(owner_repo, message, tree_sha, parents, info):
    """创建一个提交。"""
    body = {
        "message": message,
        "tree": tree_sha,
        "parents": parents,
        "author": {"name": info["author_name"], "email": info["author_email"],
                   "date": info["author_date"]},
        "committer": {"name": info["committer_name"], "email": info["committer_email"],
                      "date": info["committer_date"]},
    }
    return gh_api("repos/%s/git/commits" % owner_repo, "POST", body)["sha"]


def repo_is_empty(owner_repo):
    """看看远程仓库是不是还没有任何提交。"""
    try:
        gh_api("repos/%s/git/refs/heads/main" % owner_repo)
        return False
    except RuntimeError:
        return True


def bootstrap_first_commit(owner_repo, path):
    """空仓库没法直接创建 blob，先用 Contents API 建一个根提交。

    拿第一个提交里的第一个文件当种子，这样后面的历史就能正常往上叠了。
    """
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    gh_api("repos/%s/contents/%s" % (owner_repo, path), "PUT",
           {"message": "Initial commit", "content": content})
    print("  已创建根提交（%s）" % path)


def remote_subjects(owner_repo, branch):
    """拿远程已有的提交说明（从旧到新），用来判断哪些已经推过了。"""
    try:
        commits = gh_api("repos/%s/commits?sha=%s&per_page=100" % (owner_repo, branch))
    except RuntimeError:
        return []

    subjects = []
    for item in reversed(commits):     # API 返回是从新到旧，反过来
        subjects.append(item["commit"]["message"].splitlines()[0])
    return subjects


def main():
    if len(sys.argv) < 2:
        print("用法：python scripts/push_via_api.py <owner/repo> [分支名]")
        return 2

    owner_repo = sys.argv[1]
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"

    shas = get_history(branch)
    subjects = [commit_info(sha)["message"].splitlines()[0] for sha in shas]

    # 远程已经推过的部分跳过，只推新增的（这样重复运行也不会重传一遍）
    pushed = remote_subjects(owner_repo, branch)
    common = 0
    while common < len(pushed) and common < len(subjects) and pushed[common] == subjects[common]:
        common += 1

    if common == len(shas):
        print("远程已经是最新的了，不用推")
        return 0

    print("共 %d 个提交，前 %d 个已经在远程，这次推 %d 个"
          % (len(shas), common, len(shas) - common))

    if common == 0 and repo_is_empty(owner_repo):
        first_files = changed_files(shas[0])
        bootstrap_first_commit(owner_repo, first_files[0][1])

    # 从远程已有的最后一个提交接着往下建
    parent_sha = None
    base_tree = None
    if common > 0:
        remote_head = gh_api("repos/%s/git/refs/heads/%s" % (owner_repo, branch))
        parent_sha = remote_head["object"]["sha"]
        base_tree = gh_api("repos/%s/git/commits/%s" % (owner_repo, parent_sha))["tree"]["sha"]
        print("  从远程提交 %s 继续" % parent_sha[:10])

    for index, sha in enumerate(shas[common:], start=common + 1):
        info = commit_info(sha)
        subject = info["message"].splitlines()[0]
        entries = []

        for status, path in changed_files(sha):
            if status == "D":
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            else:
                entries.append({"path": path, "mode": "100644", "type": "blob",
                                "sha": make_blob(owner_repo, path)})

        if entries:
            base_tree = make_tree(owner_repo, entries, base_tree)

        parents = [parent_sha] if parent_sha else []
        parent_sha = make_commit(owner_repo, info["message"], base_tree, parents, info)
        print("  [%2d/%d] %s  ->  %s" % (index, len(shas), subject[:44], parent_sha[:10]))

    # 更新分支指向最后一个提交
    try:
        gh_api("repos/%s/git/refs/heads/%s" % (owner_repo, branch), "PATCH",
               {"sha": parent_sha, "force": True})
    except RuntimeError:
        # 分支还不存在，新建一个
        gh_api("repos/%s/git/refs" % owner_repo, "POST",
               {"ref": "refs/heads/%s" % branch, "sha": parent_sha})

    print("推送完成：https://github.com/%s/tree/%s" % (owner_repo, branch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
