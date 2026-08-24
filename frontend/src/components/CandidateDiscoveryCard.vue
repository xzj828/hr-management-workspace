<script setup>
import AppIcon from '@/components/AppIcon.vue'

defineProps({
  candidate: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})
defineEmits(['toggle', 'open'])
</script>

<template>
  <article :class="['discovery-card', { 'is-selected': selected, 'is-imported': candidate.imported_candidate }]" @click="$emit('open', candidate)">
    <header>
      <label class="discovery-check" @click.stop>
        <input
          type="checkbox"
          :checked="selected"
          :disabled="Boolean(candidate.imported_candidate)"
          :data-test="`discovery-check-${candidate.id}`"
          @change="$emit('toggle', candidate.id)"
        />
        <span></span>
      </label>
      <div class="discovery-avatar"><AppIcon name="user" :size="18" /></div>
      <div class="discovery-card__identity">
        <strong>{{ candidate.display_name }}</strong>
        <small>{{ candidate.current_title || '岗位信息待补充' }} · {{ candidate.city || '城市待补充' }}</small>
      </div>
      <span class="discovery-source">{{ candidate.source_label }}</span>
    </header>
    <p>{{ candidate.advantage || candidate.experience || 'BOSS 暂未展示候选人优势信息' }}</p>
    <div v-if="candidate.tags?.length" class="discovery-tags">
      <span v-for="tag in candidate.tags.slice(0, 5)" :key="tag">{{ tag }}</span>
    </div>
    <footer>
      <span><AppIcon name="briefcase" :size="13" />{{ candidate.job_title }}</span>
      <span v-if="candidate.imported_candidate" class="is-done"><AppIcon name="check-circle" :size="13" />已入库</span>
      <span v-else>{{ candidate.identity_quality === 'platform' ? '平台身份' : '待发送前核验' }}</span>
    </footer>
  </article>
</template>
