<template>
  <figure class="video">
    <div class="video-frame">
      <video
        v-if="loaded"
        ref="el"
        class="video-el"
        controls
        playsinline
        preload="metadata"
        :src="src"
        :aria-label="`参考成片: ${SITE.video.title}`"
      />
      <div v-else class="video-poster">
        <!-- 用成片的真实一帧作底, 上面压一层深色面板保证文字对比度稳定 -->
        <img
          class="video-poster-shot"
          :src="coverSrc"
          alt=""
          aria-hidden="true"
          loading="lazy"
          decoding="async"
        >
        <div class="video-poster-body">
          <p class="video-poster-kicker">参考成片</p>
          <p class="video-poster-title">{{ SITE.video.title }}</p>
          <p class="video-poster-note">
            这段视频有 {{ SITE.video.sizeHint }}, 不会自动加载, 需要你确认一次才开始下载
          </p>
          <ConfirmButton label="加载并播放视频" confirm-label="确认加载" @confirm="load" />
        </div>
      </div>
    </div>
    <figcaption class="video-cap">
      <strong>{{ SITE.video.title }}</strong>
      <span>{{ SITE.video.note }}</span>
    </figcaption>
  </figure>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { SITE } from '~/constants/site'

const assetUrl = useAssetUrl()
// 视频与封面图都放在 site/resource/video/ 下, 用相对目录引入, 不重复拷进 public/
const src = assetUrl(`resource/video/${SITE.video.file}`)
// 封面图与视频同名, 只换后缀, 这样换视频时不必再记一处要改的地方
const coverSrc = assetUrl(`resource/video/${SITE.video.file.replace(/\.mp4$/, '-cover.png')}`)

const loaded = ref(false)
const el = ref<HTMLVideoElement | null>(null)

async function load() {
  loaded.value = true
  await nextTick()
  // 用户刚点过确认按钮, 这里有用户手势, 播放不会被浏览器拦截
  try {
    await el.value?.play()
  } catch {
    // 自动播放被拒时就停在第一帧, 让用户自己点播放
  }
}
</script>
