/** 图表配色：饼图与旁边的排行榜共用同一份，色点和扇区一定对得上。 */
export const PIE_COLORS = [
  '#a78bfa', '#f0abfc', '#f472b6', '#818cf8',
  '#38bdf8', '#3fbd9d', '#fbbf24', '#fb7185',
  '#a3e635', '#c4b5fd',
]

export const pieColor = (i: number) => PIE_COLORS[i % PIE_COLORS.length]
