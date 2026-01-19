from nonebot.plugin import PluginMetadata
from .main import Config

__plugin_meta__ = PluginMetadata(
    name="BitTorrent磁力搜索",
    description="适配NoneBot的磁力搜索插件，通过机器人帮你寻找电影、软件或者学习资料",
    usage="bt （排序方式） [关键词]",
    type="application",
    homepage="https://github.com/NightDust981989/nonebot-plugin-BitTorrents",
    config=Config,
)

from . import main