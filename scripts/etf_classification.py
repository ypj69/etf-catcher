from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Classification:
    asset_class: str
    category_l1: str
    category_l2: str
    classification_rule: str
    classification_confidence: str
    review_status: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def hit(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def result(asset: str, l1: str, l2: str, rule: str, confidence: str = "high") -> Classification:
    review = "auto_approved" if confidence == "high" else "needs_review"
    return Classification(asset, l1, l2, rule, confidence, review)


def classify_etf(name: str, fund_type: str = "") -> Classification:
    text = name.upper().replace("ＥＴＦ", "ETF")
    marker = text.find("ETF")
    if marker >= 0:
        text = text[: marker + 3]
    if "货币型" in fund_type or hit(text, ("货币ETF", "现金ETF", "保证金ETF", "交易型货币")):
        return result("货币", "货币", "货币ETF", "asset.currency")
    if "固收" in fund_type or hit(text, ("国债", "政金债", "信用债", "公司债", "城投债", "可转债", "债券ETF", "利率债")):
        sub = "可转债" if "可转债" in text else "信用债" if hit(text, ("信用债", "公司债", "城投债")) else "政策性金融债" if "政金债" in text else "利率债与国债"
        return result("债券", "债券", sub, "asset.bond")
    if hit(text, ("黄金ETF", "金ETF", "白银ETF", "豆粕ETF", "有色期货", "能源化工ETF", "商品ETF")):
        sub = "黄金" if "黄金" in text or "金ETF" in text else "其他商品"
        return result("商品", "商品", sub, "asset.commodity")
    if "海外股票" in fund_type or hit(text, ("港股", "恒生", "香港", "沪港深", "沪深港", "纳指", "纳斯达克", "标普", "道琼斯", "日经", "德国", "法国", "沙特", "印度", "东南亚", "中概", "海外", "全球")):
        sub = "港股" if hit(text, ("港股", "恒生", "香港", "沪港深", "沪深港", "中概")) else "美国" if hit(text, ("纳指", "纳斯达克", "标普", "道琼斯", "美国")) else "日本" if hit(text, ("日经", "日本")) else "欧洲" if hit(text, ("德国", "法国", "欧洲")) else "新兴市场" if hit(text, ("沙特", "印度", "东南亚", "新兴")) else "全球及其他"
        return result("跨境权益", "QDII", sub, "asset.overseas")

    groups = (
        ("A股行业", "行业", "科技（半导体）", "industry.semiconductor", ("半导体", "芯片", "集成电路")),
        ("A股行业", "行业", "科技（计算机与AI）", "industry.computer_ai", ("人工智能", "AIETF", "机器人", "计算机", "软件", "云计算", "大数据", "互联网", "信创", "数字经济", "信息安全", "信息技术", "信息科技", "科创信息", "物联网", "TMT", "科技ETF", "科技50", "科技100", "科技先锋", "VR")),
        ("A股行业", "行业", "科技（通信）", "industry.telecom", ("通信", "电信", "5G", "光通信")),
        ("A股行业", "行业", "科技（电子）", "industry.electronics", ("电子ETF", "电子50", "消费电子", "电子信息", "消电ETF")),
        ("A股行业", "行业", "消费（医药生物）", "industry.healthcare", ("医药", "医疗", "生物", "创新药", "疫苗", "中药", "药ETF")),
        ("A股行业", "行业", "消费（食品饮料）", "industry.consumer", ("酒ETF", "白酒", "食品", "饮料", "消费ETF", "消费50", "消费龙头")),
        ("A股行业", "行业", "消费（汽车）", "industry.auto", ("汽车", "智能车", "新能源车")),
        ("A股行业", "行业", "消费（家电）", "industry.appliance", ("家电", "家用电器")),
        ("A股行业", "行业", "消费（农林牧渔）", "industry.agriculture", ("农业", "农牧", "农牧渔", "养殖", "畜牧", "种业", "粮食")),
        ("A股行业", "行业", "消费（服务与传媒）", "industry.services_media", ("旅游", "酒店", "零售", "商贸", "消费服务", "传媒", "游戏", "影视", "教育", "养老", "国货")),
        ("A股行业", "行业", "金融地产（证券）", "industry.broker", ("证券", "券商")),
        ("A股行业", "行业", "金融地产（银行）", "industry.bank", ("银行",)),
        ("A股行业", "行业", "金融地产（综合）", "industry.finance_property", ("金融", "保险", "地产", "房地产")),
        ("A股行业", "行业", "制造（新能源）", "industry.new_energy", ("光伏", "新能源", "电池", "储能", "锂电", "风电", "绿电", "电网", "低碳", "智能电动车", "智能驾驶")),
        ("A股行业", "行业", "制造（国防军工）", "industry.defense", ("军工", "国防", "航空", "航天", "卫星", "船舶")),
        ("A股行业", "行业", "制造（机械与高端制造）", "industry.manufacturing", ("机械", "工业ETF", "工业母机", "高端制造", "高端装备", "智能制造", "工程机械", "机床", "专精特新")),
        ("A股行业", "行业", "周期（有色金属）", "industry.metals", ("有色", "稀土", "稀有金属", "黄金股", "黄金股票", "矿业", "资源ETF")),
        ("A股行业", "行业", "周期（煤炭）", "industry.coal", ("煤炭",)),
        ("A股行业", "行业", "周期（钢铁）", "industry.steel", ("钢铁",)),
        ("A股行业", "行业", "周期（化工与材料）", "industry.chemical", ("化工", "化学", "材料ETF", "新材料")),
        ("A股行业", "行业", "周期（能源）", "industry.energy", ("油气", "石油", "石化", "天然气", "能源ETF")),
        ("A股行业", "行业", "公用事业与环保", "industry.utility", ("电力", "公用事业", "环保", "碳中和")),
        ("A股行业", "行业", "交通运输", "industry.transport", ("交通", "交运", "运输", "物流", "港口")),
        ("A股行业", "行业", "建筑建材", "industry.construction", ("建筑", "建材", "基建")),
        ("A股宽基", "宽基", "宽基（大盘）", "broad.large", ("上证50", "深证50", "深证主板50", "沪深300", "深300", "中证A50", "A50ETF", "A50增强", "中证A500", "A500ETF", "A500增强", "A100ETF", "中证A100", "上证180", "深证100", "深100", "核心50", "漂亮50", "大盘ETF")),
        ("A股宽基", "宽基", "宽基（中盘）", "broad.mid", ("中证500", "500增强", "中盘ETF", "创中盘", "中创400")),
        ("A股宽基", "宽基", "宽基（小盘）", "broad.small", ("中证1000", "1000增强", "中证2000", "国证2000", "中小100", "小盘ETF", "微盘ETF", "北证50")),
        ("A股宽基", "宽基", "科技（指数）", "broad.tech", ("创业板", "科创50", "科创100", "科创200", "科创板", "科创创业", "科创增强", "科创综指增强", "双创", "创50", "创100", "创科技", "创成长")),
        ("A股宽基", "宽基", "宽基（综合）", "broad.composite", ("全指ETF", "综指ETF", "全市场ETF", "MSCI中国A", "MSCIA股", "MSCI中国", "中证800", "上证指数", "上证380", "上证580", "深证成指", "深成ETF", "A股ETF")),
        ("A股策略", "策略", "红利与高股息", "strategy.dividend", ("红利", "高股息", "股息")),
        ("A股策略", "策略", "低波动", "strategy.low_vol", ("低波", "低波动")),
        ("A股策略", "策略", "价值", "strategy.value", ("价值",)),
        ("A股策略", "策略", "质量与现金流", "strategy.quality", ("质量", "自由现金流", "现金流")),
        ("A股策略", "策略", "成长", "strategy.growth", ("成长",)),
        ("A股策略", "策略", "ESG", "strategy.esg", ("ESG", "责任", "可持续")),
        ("A股策略", "策略", "其他策略", "strategy.other", ("基本面", "等权", "增强ETF", "治理ETF", "央视50")),
    )
    for asset, l1, l2, rule, words in groups:
        if hit(text, words):
            return result(asset, l1, l2, rule)
    if hit(text, ("央企", "国企", "民企", "一带一路", "乡村振兴", "区域", "成渝", "湖北", "长三角", "杭州", "大湾区", "湾创", "G60", "长江保护", "张江", "浙商", "浙江国资", "产业升级", "战略新兴", "创新100", "主题")):
        return result("A股主题", "主题", "政策与区域主题", "theme.policy")
    asset = "A股权益待核" if "指数型-股票" in fund_type else "其他待核"
    return result(asset, "待分类", "待分类", "unresolved", "low")
