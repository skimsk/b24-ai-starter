<script setup lang="ts">
import ModulbankMark from '~/components/ModulbankMark.vue'

withDefaults(
  defineProps<{
    /** Меньший блок для шагов мастера установки (шаг «Приветствие»). */
    compact?: boolean
  }>(),
  { compact: false },
)
</script>

<template>
  <!-- Полноэкранная загрузка: 14rem; compact — тот же логотип, меньше квадрат -->
  <div
    class="rounded-2xl flex flex-col items-center justify-center gap-2 bg-white border border-[#e5f4fc] shadow-md box-border"
    :class="
      compact
        ? 'px-3 py-3 min-h-[7rem] min-w-[7rem]'
        : 'px-4 py-3.5 min-h-[14rem] min-w-[14rem]'
    "
    aria-hidden="true"
  >
    <ModulbankMark :size="compact ? 52 : 96" />
    <span
      class="font-semibold tracking-tight text-[#02245d] select-none"
      :class="compact ? 'text-[0.8rem]' : 'text-[1.35rem]'"
    >МодульБанк</span>
  </div>
</template>
