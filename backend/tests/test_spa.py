"""SPA 静态资源服务回归测试。

覆盖两条易踩坑的边界：
1. `FRONTEND_DIST` 必须解析到 <项目根>/frontend/dist（不是 backend/frontend/dist），
   否则 SPA 路由不会注册，GET / 直接 404。
2. `@app.get("/{full_path:path}")` 的 path 转换器要求至少一个字符，不匹配空路径 `/`；
   必须显式注册 `@app.get("/")`，否则首页 404。
"""
import os


def test_spa_root_serves_index_html(client):
    """GET / 应返回 200 并返回 index.html 内容（不是 404）。"""
    resp = client.get("/")
    assert resp.status_code == 200, (
        f"GET / 返回 {resp.status_code}（应为 200）。"
        "若为 404，多半是 FRONTEND_DIST 路径错或缺少 @app.get('/') 根路由。"
    )
    assert "<html" in resp.text.lower() or "<!doctype" in resp.text.lower(), (
        "GET / 返回的不是 HTML（index.html 缺失或未指向正确目录）"
    )


def test_spa_explicit_file_served(client):
    """GET /index.html 应直接返回该文件（200），走 catch-all 命中文件分支。"""
    resp = client.get("/index.html")
    assert resp.status_code == 200


def test_frontend_dist_resolves_to_project_root(client):
    """FRONTEND_DIST 必须包含前端 dist 目录；路径错一位（指到 backend/frontend/dist）会全 404。"""
    import app as app_mod
    assert os.path.isdir(app_mod.FRONTEND_DIST), (
        f"FRONTEND_DIST={app_mod.FRONTEND_DIST} 不是目录。"
        "config.py 计算 _project_root 时少往上一层——应在 backend/ 之上。"
    )