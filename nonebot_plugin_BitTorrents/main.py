import re
import base64
import urllib.parse
from typing import List, Dict
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from nonebot import on_command
from nonebot.adapters import Message
from nonebot.params import CommandArg

try:
    from pydantic import BaseModel
    from nonebot import get_plugin_config
except ImportError:
    from pydantic import BaseSettings as BaseModel
    from nonebot import get_driver

# ========== 1. 配置映射类（从配置文件读取参数） ==========
@dataclass
class MagnetConfig:
    """磁力搜索配置类"""
    base_url: str = "https://clg8.clgapp4.xyz"         # 站点基础地址
    search_path: str = "/cllj.php"                     # 搜索接口路径
    max_results: int = 3                               # 最大返回结果数
    request_timeout: int = 15                          # 请求超时时间（秒）
    captcha_cookies: Dict[str, str] = None             # 验证Cookie（固定值）

    def __post_init__(self):
        # 初始化固定验证Cookie
        self.captcha_cookies = {
            "sssfwz": "qwsdsddsdsdse"
        }
        # 处理base_url结尾的/（统一格式：不带结尾/）
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        # 处理search_path开头的/（统一格式：带开头/）
        if not self.search_path.startswith("/"):
            self.search_path = f"/{self.search_path}"

# ========== 2. 核心工具类 ==========
class MagnetUtils:
    @staticmethod
    def decrypt_base64(encrypted_str: str) -> str:
        """Base64解密"""
        try:
            encrypted_str = encrypted_str.ljust(len(encrypted_str) + (4 - len(encrypted_str) % 4) % 4, '=')
            decoded = base64.b64decode(encrypted_str).decode('utf-8', errors='ignore')
            return urllib.parse.unquote(decoded)
        except Exception as e:
            print(f"Base64解密失败：{str(e)}")
            return ""

    @staticmethod
    def get_full_url(base_url: str, relative_url: str) -> str:
        """拼接完整URL"""
        if relative_url.startswith("http"):
            return relative_url
        if relative_url.startswith("./"):
            return f"{base_url}/{relative_url[2:]}"
        if relative_url.startswith("/"):
            return f"{base_url}{relative_url}"
        return f"{base_url}/{relative_url}"
    
    @staticmethod
    def get_sort_param(sort_keyword: str) -> str:
        """
        排序关键词
        """
        sort_mapping = {
            "相关度": "",
            "大小": "length",
            "文件大小": "length",
            "热门": "hot",
            "热门程度": "hot",
            "时间": "time",
            "最新": "time",
        }
        # 提高鲁棒性
        sort_keyword = sort_keyword.strip().lower()
        for key, value in sort_mapping.items():
            if key.lower() == sort_keyword:
                return value
        # 匹配不到返回空
        return ""

# ========== 3. 核心搜索服务 ==========
class MagnetSearchService:
    def __init__(self, config: MagnetConfig):
        self.config = config
        self.client: httpx.AsyncClient = None

    async def _init_client(self):
        """初始化客户端"""
        if self.client is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; U; Android 2.2; en-us; Droid Build/FRG22D) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Origin": self.config.base_url,
                "Referer": self.config.base_url
            }

            self.client = httpx.AsyncClient(
                headers=headers,
                cookies=self.config.captcha_cookies,
                timeout=self.config.request_timeout,  # 从配置读取超时时间
                follow_redirects=False,              # 关闭自动重定向
                verify=False
            )

    async def close_client(self):
        """关闭客户端"""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def search(self, keyword: str, sort_param: str = "") -> List[str]:
        """搜索逻辑：使用配置文件的站点/接口/结果数"""
        # 确保客户端已初始化
        await self._init_client()
        results = []

        try:
            # ========== 构造搜索URL ==========
            search_url = f"{self.config.base_url}{self.config.search_path}?name={urllib.parse.quote(keyword)}"
            # 拼接排序参数
            if sort_param:
                search_url += f"&sort={sort_param}"
            print(f"GET请求：{search_url}")
            
            # 发起请求
            response = await self.client.get(search_url)
            print(f"响应状态码：{response.status_code}")
            
            # 提取原始响应
            raw_html = response.text
            decrypted_html = raw_html

            # ========== 提取xq.php链接（使用配置） ==========
            soup = BeautifulSoup(decrypted_html, "lxml")
            result_container = soup.find("ul", id="Search_list_wrapper")
            if not result_container:
                print(f"无搜索结果容器")
                return []

            detail_links = []
            processed_urls = set()
            # 遍历结果：最多取配置的max_results条
            for idx, li in enumerate(result_container.find_all("li")):
                if idx >= self.config.max_results:
                    break
                if li.find("ul", class_="pagination"):
                    continue

                form_tag = li.find("form", action=re.compile(r"xq\.php"))
                if not form_tag:
                    continue
                key_input = form_tag.find("input", attrs={"name": "key"})
                if not key_input:
                    continue
                key = key_input.get("value", "").strip()
                if not key:
                    continue

                full_url = MagnetUtils.get_full_url(self.config.base_url, "/xq.php")
                
                # key去重
                if key in processed_urls:
                    continue
                processed_urls.add(key)

                # 提取基础信息
                title = form_tag.text.strip() or f"搜索结果{idx+1}"
                size = re.search(r"文件大小：([0-9.]+ [GMK]B)", li.text)
                size = size.group(1).strip() if size else "未知大小"
                create_time = re.search(r"创建时间：(\d{4}-\d{2}-\d{2})", li.text)
                create_time = create_time.group(1).strip() if create_time else "未知时间"

                detail_links.append({
                    "url": full_url,
                    "key": key,
                    "title": title,
                    "size": size,
                    "create_time": create_time
                })

            if not detail_links:
                return []

            # ========== 解析详情页 ==========
            for link in detail_links:
                try:
                    # 改为POST
                    detail_resp = await self.client.post(
                        link["url"],
                        data={"key": link["key"]}
                    )
                    detail_html = detail_resp.text

                    # 提取磁力链接
                    detail_soup = BeautifulSoup(detail_html, "lxml")
                    magnet_link = None
                    magnet_a = detail_soup.find("a", href=re.compile(r"magnet:\?xt=urn:btih:"))
                    if magnet_a:
                        magnet_link = magnet_a.get("href").strip()
                    if not magnet_link:
                        magnet_match = re.search(r"magnet:\?xt=urn:btih:[a-fA-F0-9]{40,}[^\"']*", detail_html)
                        if magnet_match:
                            magnet_link = magnet_match.group().strip()

                    # 构造结果
                    results.append(
                        f"标题：{link['title']}\n"
                        f"磁力链接：{magnet_link or '未提取到'}\n"
                        f"文件大小：{link['size']}\n"
                        f"收录时间：{link['create_time']}"
                    )
                except Exception as e:
                    results.append(f"标题：{link['title']}\n解析失败：{str(e)[:30]}\n文件大小：{link['size']}")

        except Exception as e:
            print(f"搜索异常：{str(e)}")
            results = [f"搜索失败：{str(e)[:50]}"]

        return results

# ========== 4. 配置类定义 ==========
class Config(BaseModel):
    magnet_base_url: str = "https://clg8.clgapp4.xyz"
    magnet_search_path: str = "/cllj.php"
    magnet_max_results: int = 3
    magnet_request_timeout: int = 15

try:
    plugin_config = get_plugin_config(Config)
except:
    # 兜底
    from nonebot import get_driver
    driver = get_driver()
    global_config = driver.config
    plugin_config = Config(**global_config.dict())

# 初始化配置类
magnet_config = MagnetConfig(
    base_url=plugin_config.magnet_base_url,
    search_path=plugin_config.magnet_search_path,
    max_results=plugin_config.magnet_max_results,
    request_timeout=plugin_config.magnet_request_timeout
)
search_service = MagnetSearchService(magnet_config)

print(f"磁力搜索插件初始化完成，使用站点：{magnet_config.base_url}{magnet_config.search_path}")

# ========== 5. 注册命令处理器 ==========
bt_cmd = on_command("bt", aliases=set(), priority=10, block=True)

@bt_cmd.handle()
async def handle_bt_command(args: Message = CommandArg()):
    message = str(args).strip()
    args_list = message.split()
    
    # 检查参数是否足够
    if not message or len(args_list) < 1:
        await bt_cmd.finish("用法：bt （排序方式） [关键词]\n示例：bt 热门 安达与岛村")
    
    # 解析排序参数和关键词
    sort_keyword = ""
    keyword = ""
    if len(args_list) == 1:
        # 默认相关度
        keyword = args_list[0]
    else:
        # 有排序参数
        sort_keyword = args_list[0]
        keyword = " ".join(args_list[1:])
    
    # 转换排序关键词为sort
    sort_param = MagnetUtils.get_sort_param(sort_keyword)
    # 执行搜索
    results = await search_service.search(keyword, sort_param)

    if not results:
        # 无结果
        await bt_cmd.finish("未找到相关磁力链接，网站失效或网络问题")
    else:
        # 有结果时拼接完整内容
        result_text = f"共找到 {len(results)} 条有效结果：\n"
        for idx, res in enumerate(results, 1):
            result_text += f"\n===== 结果 {idx} =====\n{res}"
        
        await bt_cmd.finish(result_text)