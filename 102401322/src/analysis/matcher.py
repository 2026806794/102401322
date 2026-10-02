"""多模式匹配（Aho-Corasick 自动机）。

为什么需要它：统计"每条弹幕属于哪个领域 / 提到了哪个产品"的时候，
最直接的写法是两层循环：

    for 每条弹幕:
        for 每个类别:
            for 每个别名:
                if 别名 in 弹幕: 计数 + 1

我的词典有 433 个别名，弹幕有 6 万多条，这样算下来要几秒钟。
所以换成了 AC 自动机：把所有别名建成一棵树，一次扫描就能同时找出所有命中的词。

原理（数据结构课上学过，这里自己实现了一遍）：
    1. 建 Trie：把所有模式串插到一棵树上，每个节点是一个字符；
    2. 补失败指针：用 BFS 遍历，每个节点的 fail 指向"最长后缀"所在的节点。
       这样匹配时如果当前字符走不通，就顺着 fail 跳，不用从头重新匹配；
    3. 合并输出：把 fail 节点上的输出也并到当前节点，匹配时就不用顺着 fail 链
       一个个找了。

复杂度从 O(文本长度 × 模式数) 降到 O(文本长度 + 命中数)。
实测（3000 条弹幕、433 个模式）比朴素写法快 18 倍左右。
"""


class AhoCorasick:
    """多模式匹配自动机。

    patterns 是 (模式, 标签) 的列表。同一个模式可以对应多个标签
    （比如"算力"既算硬件成本也算硬件算力领域）。
    """

    def __init__(self, patterns):
        # 用列表存节点，每个节点是一个字典：字符 -> 子节点编号
        # 第 0 个节点是根
        self.children = [{}]
        self.fail = [0]        # 每个节点的失败指针
        self.outputs = [[]]    # 每个节点上挂了哪些标签
        self.pattern_count = 0

        for pattern, label in patterns:
            if pattern:
                self._insert(pattern, label)

        self._build_fail()

    def _insert(self, pattern, label):
        """把一个模式插到 Trie 里。"""
        node = 0
        for char in pattern:
            if char not in self.children[node]:
                # 需要新建节点
                self.children.append({})
                self.fail.append(0)
                self.outputs.append([])
                self.children[node][char] = len(self.children) - 1
            node = self.children[node][char]

        if label not in self.outputs[node]:
            self.outputs[node].append(label)
        self.pattern_count += 1

    def _build_fail(self):
        """用 BFS 建失败指针。

        根节点的直接子节点 fail 都指向根。其他节点：假设父节点是 p，当前字符是 c，
        就沿着 p 的 fail 往上找，看哪个祖先有 c 这个子节点，那个子节点就是当前节点的 fail。
        """
        queue = []
        # 第一层：fail 都指向根
        for char in self.children[0]:
            child = self.children[0][char]
            self.fail[child] = 0
            queue.append(child)

        head = 0
        while head < len(queue):
            node = queue[head]
            head += 1

            for char, child in self.children[node].items():
                # 从父节点的 fail 开始往上找
                fallback = self.fail[node]
                while fallback and char not in self.children[fallback]:
                    fallback = self.fail[fallback]
                if char in self.children[fallback]:
                    self.fail[child] = self.children[fallback][char]
                else:
                    self.fail[child] = 0

                # 把 fail 节点的输出合并过来，匹配时就不用再顺着 fail 链找了
                for label in self.outputs[self.fail[child]]:
                    if label not in self.outputs[child]:
                        self.outputs[child].append(label)

                queue.append(child)

    def find_labels(self, text):
        """找出文本里命中了哪些标签（去重）。"""
        labels = set()
        node = 0
        for char in text:
            # 走不通就顺着 fail 跳
            while node and char not in self.children[node]:
                node = self.fail[node]
            node = self.children[node].get(char, 0)
            if self.outputs[node]:
                labels.update(self.outputs[node])
        return labels

    def count_labels(self, texts):
        """统计每个标签在多少条文本里出现过（同一条里出现多次只算一次）。"""
        counter = {}
        for text in texts:
            for label in self.find_labels(text):
                counter[label] = counter.get(label, 0) + 1
        return counter

    def count_occurrences(self, texts):
        """统计每个标签一共出现了多少次（同一条里重复出现会累加）。"""
        counter = {}
        for text in texts:
            node = 0
            for char in text:
                while node and char not in self.children[node]:
                    node = self.fail[node]
                node = self.children[node].get(char, 0)
                for label in self.outputs[node]:
                    counter[label] = counter.get(label, 0) + 1
        return counter

    def find_matches(self, text):
        """返回 [(结束位置, 标签), ...]，需要知道命中在哪儿的时候用。"""
        matches = []
        node = 0
        for index, char in enumerate(text):
            while node and char not in self.children[node]:
                node = self.fail[node]
            node = self.children[node].get(char, 0)
            for label in self.outputs[node]:
                matches.append((index, label))
        return matches

    @property
    def node_count(self):
        """自动机有多少个节点（写性能报告时用）。"""
        return len(self.children)

    def __len__(self):
        return self.pattern_count


def naive_match_count(texts, patterns):
    """朴素写法：一个个别名去做 in 判断。

    这个只用来做性能对比和测试里的"标准答案"，实际统计走 AhoCorasick。
    """
    # 先按标签把别名归拢一下
    grouped = {}
    for pattern, label in patterns:
        if label not in grouped:
            grouped[label] = []
        grouped[label].append(pattern)

    counter = {}
    for text in texts:
        for label, aliases in grouped.items():
            for alias in aliases:
                if alias in text:
                    counter[label] = counter.get(label, 0) + 1
                    break
    return counter
