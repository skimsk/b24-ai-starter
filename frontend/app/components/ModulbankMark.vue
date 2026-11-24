<script setup lang="ts">
/**
 * Знак Модульбанка: сетка 5×5 из цветных квадратов, как на официальном логотипе.
 * Цвета сняты с логотипа банка; пустые клетки — прозрачные.
 */
withDefaults(defineProps<{ size?: number | string }>(), { size: 48 })

const L = '#5acef6' // голубой
const N = '#02245d' // тёмно-синий
const Y = '#d0d501' // салатовый
const G = '#5eb900' // зелёный
const B = '#0299e5' // синий

const GRID: (string | null)[][] = [
  [L, null, N, L, null],
  [Y, G, null, B, G],
  [null, L, Y, null, L],
  [N, B, null, Y, null],
  [L, null, G, null, B],
]

const cells = GRID.flatMap((row, y) =>
  row.map((fill, x) => (fill ? { x, y, fill } : null)).filter(Boolean),
) as { x: number; y: number; fill: string }[]
</script>

<template>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 50 50"
    :width="size"
    :height="size"
    role="img"
    aria-label="Модульбанк"
  >
    <rect
      v-for="cell in cells"
      :key="`${cell.x}-${cell.y}`"
      :x="cell.x * 10"
      :y="cell.y * 10"
      width="10"
      height="10"
      :fill="cell.fill"
    />
  </svg>
</template>
