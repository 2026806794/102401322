"""两个 HTML 页面（大屏、趋势报告）共用的部分。

echarts 的引入和初始化脚本两边是一样的，抽出来放在这里，
免得改一处忘一处。
"""

# 引入本地的 echarts（放在 output/assets 下，断网也能打开）
ECHARTS_SCRIPT_TAG = '<script src="../assets/echarts.min.js"></script>'

# 页面加载完之后，把 CHARTS 里的配置逐个渲染到对应的 div 上。
#
# 注意大括号：这个常量自己要用 .format(charts_json=...) 格式化一次，
# 所以 {charts_json} 是占位符，而 JS 代码里的花括号要写成双份 {{ }} 转义。
# 不能把它直接塞进 HTML 模板的 format 里——那样替换进去的值不会再被解析一遍，
# 花括号会原样留在页面上，JS 就报错了（这里踩过一次坑）。
ECHARTS_INIT_SCRIPT = """<script>
  const CHARTS = {charts_json};
  Object.keys(CHARTS).forEach(function (key) {{
    const dom = document.getElementById(key);
    if (!dom) return;
    const chart = echarts.init(dom, null, {{renderer: 'canvas'}});
    chart.setOption(CHARTS[key]);
    window.addEventListener('resize', function () {{ chart.resize(); }});
  }});
</script>"""
