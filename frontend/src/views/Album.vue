<template>
  <div class="page">
    <div class="head">
      <div v-if="!active">
        <div class="page-title">相册</div>
        <div class="page-sub">照片原图加密存储 · 分组管理</div>
      </div>
      <div v-else>
        <div class="page-title">{{ curAlbum?.name || '相册' }}</div>
        <div class="page-sub">{{ curAlbum?.note }} · 共 {{ photos.length }} 张</div>
      </div>
      <div class="actions">
        <el-button v-if="active" @click="back">‹ 返回相册列表</el-button>
        <el-button type="primary" @click="uploadOpen = true">
          <el-icon style="margin-right:4px"><Upload /></el-icon>{{ active ? '上传照片' : '上传' }}
        </el-button>
        <el-button v-if="!active" @click="openAlbumDialog()">新建相册</el-button>
        <el-button v-if="!active" @click="trashOpen = true">回收站</el-button>
        <template v-if="active">
          <el-button @click="openAlbumDialog(curAlbum)">重命名</el-button>
          <el-button type="danger" plain @click="delAlbum">删除相册</el-button>
        </template>
      </div>
    </div>

    <!-- 相册网格 -->
    <div v-if="!active" class="grid albums">
      <div v-for="a in albums" :key="a.id" class="album-card glass" @click="enter(a.id)">
        <div class="a-cover"><el-icon :size="34" color="rgba(139,92,246,.6)"><Picture /></el-icon></div>
        <div class="a-name">{{ a.name }}</div>
        <div class="a-note">{{ a.note || `${a.count} 张` }}</div>
      </div>
      <div v-if="!albums.length" class="full-empty">
        <EmptyState icon="Picture" title="还没有相册" desc="先建一个相册，把照片传上来 —— 原图会加密存储。">
          <template #default>
            <el-button type="primary" round style="margin-top:16px" @click="openAlbumDialog()">新建相册</el-button>
          </template>
        </EmptyState>
      </div>
    </div>

    <!-- 照片墙 -->
    <div v-else class="grid photos">
      <div v-for="(ph, i) in photos" :key="ph.id" class="photo-wrap glass">
        <img :src="ensureUrl(ph)" loading="lazy" @click="light = i" />
        <div class="p-ops">
          <el-button text circle size="small" title="下载" @click="download(ph)"><el-icon><Download /></el-icon></el-button>
          <el-button text circle size="small" type="danger" @click="delPhoto(ph)"><el-icon><Delete /></el-icon></el-button>
        </div>
      </div>
      <div v-if="!photos.length" class="full-empty">
        <EmptyState icon="Picture" title="相册还是空的" desc="点右上角「上传照片」选择图片（jpg/png/webp/gif，单张 ≤20MB，可多选）。" />
      </div>
    </div>

    <!-- 相册弹窗 -->
    <el-dialog v-model="albumOpen" :title="albumForm.id ? '重命名相册' : '新建相册'" width="420px">
      <el-form label-position="top">
        <el-form-item label="相册名"><el-input v-model="albumForm.name" placeholder="如：日常 / 证书 / 旅行" /></el-form-item>
        <el-form-item label="说明（可空）"><el-input v-model="albumForm.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="albumOpen = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="saveAlbum">保存</el-button>
      </template>
    </el-dialog>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadOpen" :title="active ? `上传到「${curAlbum?.name}」` : '上传照片'" width="480px">
      <el-upload drag multiple :auto-upload="false" :limit="0" accept="image/*" class="up"
        :on-change="onPick" :file-list="[]">
        <div style="padding: 14px">拖拽或点击选择图片（可多选）</div>
      </el-upload>
      <p v-if="pending.length" class="cnt">已选 {{ pending.length }} 张：{{ pending.map((f) => f.name).join('、') }}</p>
      <template #footer>
        <el-button @click="uploadOpen = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!pending.length || !active" @click="doUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 灯箱 -->
    <div v-if="light !== null" class="lightbox" @click.self="light = null">
      <div class="lb-head">
        <span>{{ light + 1 }} / {{ photos.length }}</span>
        <div>
          <el-button text circle @click="download(photos[light])"><el-icon color="#fff"><Download /></el-icon></el-button>
          <el-button text circle type="danger" @click="delPhoto(photos[light], true)"><el-icon color="#fff"><Delete /></el-icon></el-button>
          <el-button text circle @click="light = null"><el-icon color="#fff"><Close /></el-icon></el-button>
        </div>
      </div>
      <img :src="ensureUrl(photos[light])" @click="light = null" />
      <button v-if="light > 0" class="lb-nav prev" @click.stop="light--"><el-icon><ArrowLeft /></el-icon></button>
      <button v-if="light < photos.length - 1" class="lb-nav next" @click.stop="light++"><el-icon><ArrowRight /></el-icon></button>
    </div>
    <TrashDialog v-model="trashOpen" @restored="loadAlbums" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Picture, Download, Delete, Close, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { http } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import TrashDialog from '../components/TrashDialog.vue'

const trashOpen = ref(false)

interface Album { id: string; name: string; note: string; count: number }
interface Photo { id: string; ext: string; added: string; size: number }
type Picked = { raw: File; name: string }

const albums = ref<Album[]>([])
const active = ref('')
const photos = ref<Photo[]>([])
const curAlbum = ref<Album | null>(null)
const busy = ref(false)
const uploading = ref(false)
const albumOpen = ref(false)
const uploadOpen = ref(false)
const pending = ref<Picked[]>([])
const light = ref<number | null>(null)
const urls = ref<Record<string, string>>({})
const albumForm = reactive({ id: '', name: '', note: '' })

function onPick(f: { raw?: File; name: string }) {
  if (f.raw) pending.value.push({ raw: f.raw, name: f.raw.name || f.name })
}

async function loadAlbums() {
  try {
    const r = await http.get<{ albums: Album[] }>('/album')
    albums.value = r.albums
  } catch { /* ignore */ }
}

async function enter(id: string) {
  active.value = id
  urls.value = {}
  try {
    const r = await http.get<{ album: Album; photos: Photo[] }>(`/album/${id}`)
    curAlbum.value = r.album
    photos.value = r.photos
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '打开失败')
    back()
  }
}

function back() {
  active.value = ''
  curAlbum.value = null
  photos.value = []
  urls.value = {}
  light.value = null
  loadAlbums()
}

function openAlbumDialog(a?: Album | null) {
  albumForm.id = a?.id || ''
  albumForm.name = a?.name || ''
  albumForm.note = a?.note || ''
  albumOpen.value = true
}

async function saveAlbum() {
  if (!albumForm.name.trim()) return ElMessage.warning('请填写相册名')
  busy.value = true
  const body = { name: albumForm.name.trim(), note: albumForm.note.trim() }
  try {
    if (albumForm.id) await http.put(`/album/${albumForm.id}`, body)
    else await http.post('/album', body)
    albumOpen.value = false
    await loadAlbums()
    if (albumForm.id && active.value) enter(active.value)
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { busy.value = false }
}

async function delAlbum() {
  if (!curAlbum.value) return
  try {
    await ElMessageBox.confirm(`删除相册「${curAlbum.value.name}」及其全部照片？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/album/${active.value}`)
    ElMessage.success('已删除')
    back()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function doUpload() {
  if (!active.value || !pending.value.length) return
  uploading.value = true
  try {
    const fd = new FormData()
    pending.value.forEach((p) => fd.append('files', p.raw))
    await http.post(`/album/${active.value}/photos`, fd)
    ElMessage.success(`已上传 ${pending.value.length} 张`)
    pending.value = []
    uploadOpen.value = false
    await enter(active.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally { uploading.value = false }
}

function ensureUrl(ph: Photo | undefined): string {
  if (!ph) return ''
  if (urls.value[ph.id] !== undefined) return urls.value[ph.id]
  urls.value[ph.id] = '' // 占位
  http.blob(`/album/${active.value}/photos/${ph.id}/file`)
    .then((b) => { urls.value[ph.id] = URL.createObjectURL(b) })
    .catch(() => { urls.value[ph.id] = '' })
  return ''
}

async function download(ph: Photo) {
  try {
    const b = await http.blob(`/album/${active.value}/photos/${ph.id}/file`)
    const u = URL.createObjectURL(b)
    const a = document.createElement('a')
    a.href = u
    a.download = `${ph.id}.${ph.ext}`
    a.click()
    URL.revokeObjectURL(u)
  } catch { ElMessage.error('下载失败') }
}

async function delPhoto(ph: Photo, stay = false) {
  try {
    await ElMessageBox.confirm('删除这张照片？', '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await http.del(`/album/${active.value}/photos/${ph.id}`)
    const idx = photos.value.findIndex((x) => x.id === ph.id)
    if (light.value !== null && light.value >= idx) {
      light.value = photos.value.length - 2 < idx ? null : Math.max(0, idx - 1)
    }
    if (!stay && light.value !== null) light.value = null
    await enter(active.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function onKey(e: KeyboardEvent) {
  if (light.value === null) return
  if (e.key === 'ArrowRight') light.value = Math.min(photos.value.length - 1, light.value + 1)
  else if (e.key === 'ArrowLeft') light.value = Math.max(0, light.value - 1)
  else if (e.key === 'Escape') light.value = null
}

onMounted(() => {
  loadAlbums()
  window.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; margin-top: 16px; }
.grid.photos { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.album-card { padding: 18px; text-align: center; cursor: pointer; transition: transform .15s; }
.album-card:hover { transform: translateY(-3px); box-shadow: 0 16px 44px rgba(139, 92, 246, 0.2); }
.a-cover { height: 96px; display: grid; place-items: center; }
.a-name { font-weight: 700; }
.a-note { color: var(--txt2); font-size: 12px; margin-top: 2px; }
.photo-wrap { position: relative; border-radius: 14px; overflow: hidden; padding: 0; cursor: zoom-in; }
.photo-wrap img { width: 100%; height: 170px; object-fit: cover; display: block; background: rgba(148,163,184,.15); }
.p-ops {
  position: absolute; top: 6px; right: 6px; display: flex; gap: 2px; opacity: 0;
  background: rgba(15, 23, 42, 0.55); border-radius: 8px; padding: 2px; transition: opacity .15s;
}
.photo-wrap:hover .p-ops { opacity: 1; }
.full-empty { grid-column: 1 / -1; }
.up { width: 100%; }
.cnt { color: var(--txt2); font-size: 12.5px; margin-top: 10px; }

.lightbox {
  position: fixed; inset: 0; z-index: 200; background: rgba(5, 8, 22, 0.92);
  display: flex; align-items: center; justify-content: center; cursor: zoom-out;
}
.lightbox img { max-width: 92vw; max-height: 86vh; border-radius: 8px; cursor: zoom-out; }
.lb-head { position: absolute; top: 14px; left: 0; right: 0; display: flex; justify-content: space-between; align-items: center; padding: 0 18px; color: #e8edf7; font-size: 14px; }
.lb-nav {
  position: absolute; top: 50%; transform: translateY(-50%); width: 44px; height: 60px;
  background: rgba(255, 255, 255, 0.1); border: none; color: #fff; cursor: pointer; border-radius: 10px; font-size: 18px;
}
.lb-nav.prev { left: 16px; }
.lb-nav.next { right: 16px; }
</style>
