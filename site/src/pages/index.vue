<template>
  <div>
    <section class="hero">
      <div class="wrap hero-inner">
        <div class="hero-badges">
          <span class="badge"><span class="badge-key">版本</span><b>{{ SITE.version }}</b></span>
          <span class="badge"><span class="badge-key">许可证</span><b>{{ SITE.license }}</b></span>
          <span class="badge"><span class="badge-key">画面</span><b>Python + Pillow</b></span>
          <span class="badge"><span class="badge-key">配乐</span><b>Python + NumPy</b></span>
          <span class="badge"><span class="badge-key">编码</span><b>FFmpeg</b></span>
        </div>
        <h1>让 Agent 自己<em>写代码做出成片</em></h1>
        <p class="hero-tagline">{{ SITE.tagline }}</p>
        <p v-for="(p, i) in SITE.intro" :key="i" class="hero-intro">{{ p }}</p>
        <div class="hero-actions">
          <a class="btn btn-primary" :href="SITE.releases" target="_blank" rel="noopener">
            下载技能包
          </a>
          <a class="btn btn-ghost" href="#showcase">先看参考成片</a>
          <a class="btn btn-ghost" :href="SITE.repo" target="_blank" rel="noopener">查看源码</a>
        </div>
      </div>
    </section>

    <SectionBlock
      anchor="showcase"
      kicker="Showcase"
      title="这是本技能生成的成片"
      lead="不是概念演示, 是一条完整交付的 108 秒科普解说片: 有文案, 有分镜, 有配乐, 有卡点, 有客观验收记录."
    >
      <HeroVideo />
    </SectionBlock>

    <SectionBlock
      anchor="features"
      kicker="Features"
      title="技能里有什么"
      lead="二十份方法论文档加三十五个脚本, 覆盖从拿到主题到交出成片的每一步."
    >
      <div class="grid">
        <article v-for="([name, desc], i) in CAPABILITIES" :key="i" class="card">
          <h3>{{ name }}</h3>
          <p>{{ desc }}</p>
        </article>
      </div>
    </SectionBlock>

    <SectionBlock
      anchor="flow"
      kicker="Pipeline"
      title="九个阶段, 两道确认门"
      lead="开工前确认一次 (代价, 配色, 确认模式, 是否分批, 署名, 命名), 全量渲染与最终合成前各再确认一次; 重活之前先探测核数, 负载, 内存与磁盘, 按实测限额跑. 交付节点不可省略: 配色与抽到的风格牌先合成一个方向, 出两张带色值的样图, 全量渲染前再出开头约 10 秒的带音轨样片; 每个节点都先交文件路径, 等你看完给出回执再往下走."
    >
      <div class="flow">
        <div v-for="([n, name, desc], i) in STAGES" :key="i" class="flow-row">
          <span class="flow-n">{{ n }}</span>
          <div>
            <div class="flow-name">{{ name }}</div>
            <div class="flow-desc">{{ desc }}</div>
          </div>
        </div>
      </div>
    </SectionBlock>

    <SectionBlock
      anchor="needs"
      kicker="Requirements"
      title="跑起来需要什么"
      lead="全部是本地工具, 不需要联网, 不需要 GPU, 也不需要视频生成模型."
    >
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>依赖</th>
              <th>用途</th>
              <th>缺失的后果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="([name, use, impact], i) in REQUIREMENTS" :key="i">
              <td class="td-strong">{{ name }}</td>
              <td>{{ use }}</td>
              <td>{{ impact }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </SectionBlock>

    <SectionBlock
      anchor="start"
      kicker="Quick start"
      title="装好之后先说一句话"
      lead="技能被触发后, Agent 会先做环境探测, 再走启动确认门问你时长与分辨率, 配色, 确认模式, 是否分批, 是否需要署名与交付命名, 拿到答复才开工; 之后全部按确认单执行, 中途只在重活前再确认资源."
    >
      <div class="cmd-stack">
        <CopyCommand command="用 agent-video-driver 做一条 60 秒的科普解说片, 主题是坐标系为什么有用" />
        <CopyCommand command="python scripts/check_env.py" />
      </div>
    </SectionBlock>

    <SectionBlock
      anchor="install"
      kicker="Install"
      title="三种安装方式"
      lead="技能发现深度只有一层, 所以整个 agent-video-driver 目录直接放进技能目录即可."
    >
      <div class="cmd-stack">
        <div v-for="(item, i) in INSTALLS" :key="i" class="cmd-item">
          <h4>{{ item.label }}</h4>
          <p>{{ item.hint }}</p>
          <a
            v-if="item.link === 'releases'"
            class="btn btn-primary"
            :href="SITE.releases"
            target="_blank"
            rel="noopener"
          >
            前往 Releases 取 {{ SITE.zipName }}
          </a>
          <CopyCommand v-else :command="item.command" />
        </div>
      </div>
    </SectionBlock>

    <SectionBlock
      anchor="tradeoffs"
      kicker="Tradeoffs"
      title="设计取舍"
      lead="把边界说清楚, 免得你在不合适的题材上浪费一轮."
    >
      <div class="notes">
        <p v-for="([name, desc], i) in TRADEOFFS" :key="i" class="note">
          <strong>{{ name }}</strong><br />
          <span>{{ desc }}</span>
        </p>
      </div>
    </SectionBlock>
  </div>
</template>

<script setup lang="ts">
import {
  CAPABILITIES,
  INSTALLS,
  REQUIREMENTS,
  SITE,
  STAGES,
  TRADEOFFS,
} from '~/constants/site'

useHead({
  title: `${SITE.name} - 让 Agent 自己写代码做出成片`,
  meta: [{ name: 'description', content: SITE.tagline }],
})
</script>
