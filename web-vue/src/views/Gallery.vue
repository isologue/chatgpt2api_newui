<template>
  <div class="gallery-page">
    <PagePanel class="gallery-hero">
      <PanelHeader title="图片管理">
        <template #actions>
          <Button size="sm" variant="outline" :disabled="isLoading" @click="openStorageModal">
            存储管理
          </Button>
          <Button size="sm" variant="outline" :disabled="isLoading" @click="refreshAll">
            {{ isLoading ? '刷新中...' : '刷新' }}
          </Button>
        </template>
      </PanelHeader>
      <MetricStrip
        :items="galleryMetricItems"
        columns-class="grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
        density="compact"
      />
      <FilterToolbar class="gallery-filter-grid" gap="tight" mobile-mode="stack">
        <Input
          :model-value="searchQuery"
          type="text"
          placeholder="搜索文件名、路径、标签"
          block
          root-class="gallery-filter-search"
          @update:model-value="searchQuery = $event"
        />
        <div class="gallery-filter-field gallery-filter-field--tag">
          <GroupedSelectMenu
            v-model="tagFilter"
            :options="tagOptions"
            placeholder="全部标签"
            selected-indicator="none"
          />
        </div>
        <DateRangeInputs
          v-model:start="startDate"
          v-model:end="endDate"
          class="gallery-date-range"
          input-root-class="gallery-date-input"
        />
      </FilterToolbar>
    </PagePanel>

    <PagePanel flush>
      <div class="gallery-content-toolbar">
        <div class="flex min-w-0 items-center gap-3">
          <Checkbox
            :model-value="allVisibleSelected"
            :disabled="files.length === 0 || isLoading"
            @update:model-value="toggleSelectAllVisible"
          />
          <div class="min-w-0">
            <p class="ui-section-kicker">当前视图</p>
            <p class="mt-1 text-xs text-muted-foreground">{{ paginationSummary }}</p>
          </div>
        </div>

        <ActionRow class="gallery-content-actions" gap="tight" mobile-stretch>
          <Button
            size="xs"
            variant="outline"
            :disabled="selectedCount === 0 || batchBusy"
            @click="handleBatchDownload"
          >
            批量下载
          </Button>
          <Button
            size="xs"
            variant="outline"
            :disabled="selectedCount === 0 || batchBusy"
            @click="handleDeleteSelected"
          >
            批量删除
          </Button>
          <Button
            size="xs"
            variant="ghost"
            :disabled="selectedCount === 0 || batchBusy"
            @click="clearSelection"
          >
            取消选择
          </Button>
        </ActionRow>
      </div>

      <PageLoadingState
        v-if="!hasLoadedOnce && files.length === 0"
        class="gallery-state-block"
        title="正在加载图片"
        description="读取图片记录、标签和分页数据。"
      />

      <StateBlock
        v-else-if="files.length === 0"
        class="gallery-state-block"
        :title="galleryLoadError ? '图片管理加载失败' : '暂无图片'"
        :description="galleryLoadError || '换个筛选条件或刷新后再看。'"
      >
        <template #media>
          <Icon icon="lucide:image-off" class="h-12 w-12 text-muted-foreground/40" />
        </template>
      </StateBlock>

      <div v-else class="space-y-4 p-4 lg:p-5">
        <div class="image-grid">
          <GalleryImageCard
            v-for="file in files"
            :key="file.path"
            :file="file"
            :selected="isSelected(file.path)"
            :previewable="canPreviewFile(file)"
            :copied="copiedFileKey === file.path"
            :image-url="getFileUrl(file.thumbnail_url || file.url)"
            :storage-label="storageLabel(file)"
            :size-label="formatSize(file.size)"
            :dimensions="formatDimensions(file)"
            :time-remaining="file.expires_in_seconds !== null ? formatTimeRemaining(file.expires_in_seconds) : ''"
            @preview="openPreview"
            @select="(item, checked) => toggleSelect(item.path, checked)"
            @image-error="(event, item) => handleImageError(event, item.path)"
            @copy="copyFileLink"
            @edit-tags="openTagEditor"
            @download="downloadFile"
            @delete="handleDelete"
            @tag-click="setTagFilter"
          />
        </div>

        <ListPagination
          v-model:page="currentPage"
          v-model:page-size="pageSize"
          :total-count="totalItems"
          :page-size-options="galleryPageSizeOptions"
          unit="张图片"
          :disabled="isLoading"
        />
      </div>
    </PagePanel>

    <GalleryLightbox
      :file="previewFile"
      :image-url="previewFile ? getFileUrl(previewFile.url) : ''"
      :size-label="previewFile ? formatSize(previewFile.size) : ''"
      :copied="Boolean(previewFile && copiedFileKey === previewFile.path)"
      @close="closePreview"
      @download="downloadFile"
      @copy="copyFileLink"
      @edit-tags="openTagEditor"
    />

    <GalleryTagEditorModal
      :file="tagEditorFile"
      :image-url="tagEditorFile ? getFileUrl(tagEditorFile.thumbnail_url || tagEditorFile.url) : ''"
      :draft="tagDraft"
      :draft-tags="draftTags"
      :all-tags="allTags"
      :is-saving="isTagSaving"
      @close="closeTagEditor"
      @clear="tagDraft = ''"
      @save="saveTagEditor"
      @toggle-tag="toggleDraftTag"
      @update:draft="tagDraft = $event"
    />

    <SelectionBulkBar
      :selected-count="selectedCount"
      :summary-text="`已选择 ${selectedCount} 张图片`"
      density="compact"
    >
      <Button size="xs" variant="outline" :disabled="batchBusy" @click="handleBatchDownload">下载 zip</Button>
      <Button size="xs" variant="outline" :disabled="batchBusy" @click="handleDeleteSelected">删除</Button>
      <Button size="xs" variant="ghost" :disabled="batchBusy" @click="clearSelection">取消</Button>
    </SelectionBulkBar>

    <OperationProgressModal
      :open="operationProgress.open"
      :title="operationProgress.title"
      :subtitle="operationProgress.subtitle"
      :total="operationProgress.total"
      :current="operationProgress.current"
      :status-label="operationProgress.statusLabel"
      :message="operationProgress.message"
      :error="operationProgress.error"
      :busy="operationProgress.busy"
      @close="operationProgress.open = false"
    />

    <ModalShell
      :open="isStorageModalOpen"
      max-width="38rem"
      close-on-backdrop
      @close="closeStorageModal"
    >
      <div class="gallery-storage-modal">
        <header class="gallery-storage-header">
          <div>
            <p class="ui-section-kicker">磁盘与图库</p>
            <h3>存储管理</h3>
            <p>查看图片占用、磁盘剩余空间，并执行简单清理。</p>
          </div>
          <Button size="sm" variant="ghost" icon-only aria-label="关闭存储管理" @click="closeStorageModal">
            <Icon icon="lucide:x" class="h-4 w-4" />
          </Button>
        </header>

        <ModalBody density="normal">
          <div v-if="storageActionError" class="gallery-storage-alert is-error">
            <Icon icon="lucide:circle-alert" class="h-4 w-4" />
            <span>{{ storageActionError }}</span>
          </div>
          <div v-else-if="storageActionMessage" class="gallery-storage-alert is-success">
            <Icon icon="lucide:circle-check" class="h-4 w-4" />
            <span>{{ storageActionMessage }}</span>
          </div>

          <div class="gallery-storage-grid">
            <div class="gallery-storage-card">
              <span>磁盘总量</span>
              <strong>{{ storageStats ? formatMb(storageStats.disk_total_mb) : '-' }}</strong>
            </div>
            <div class="gallery-storage-card">
              <span>已用空间</span>
              <strong>{{ storageStats ? formatMb(storageStats.disk_used_mb) : '-' }}</strong>
            </div>
            <div class="gallery-storage-card">
              <span>剩余空间</span>
              <strong>{{ storageStats ? formatMb(storageStats.disk_free_mb) : '-' }}</strong>
            </div>
            <div class="gallery-storage-card">
              <span>图库占用</span>
              <strong>{{ storageStats ? formatSize(storageStats.image_size_bytes) : formatSize(totalSize) }}</strong>
            </div>
          </div>

          <div class="gallery-storage-meter" aria-label="磁盘使用率">
            <div class="gallery-storage-meter__bar">
              <span :style="{ width: storageUsageBarWidth }"></span>
            </div>
            <div class="gallery-storage-meter__meta">
              <span>磁盘使用率</span>
              <strong>{{ storageUsagePercent }}</strong>
            </div>
          </div>

          <div class="gallery-storage-summary">
            <div>
              <span>图库文件</span>
              <strong>{{ storageStats ? `${storageStats.image_count} 个` : `${counts.all} 个` }}</strong>
            </div>
            <div>
              <span>当前筛选结果</span>
              <strong>{{ totalItems }} 个 / {{ formatSize(totalSize) }}</strong>
            </div>
          </div>

          <div class="gallery-storage-target">
            <div>
              <span>按目标剩余空间清理</span>
              <p>输入希望保留的磁盘剩余空间，系统会从旧图片开始清理。</p>
            </div>
            <Input
              :model-value="targetFreeMb"
              type="number"
              min="1"
              placeholder="500"
              root-class="gallery-storage-target-input"
              @update:model-value="targetFreeMb = String($event)"
            />
            <div class="gallery-storage-target-actions">
              <Button size="sm" variant="ghost" :disabled="isStorageBusy" @click="handleCleanupToTarget(true)">
                预估
              </Button>
              <Button size="sm" variant="outline" :disabled="isStorageBusy" @click="handleCleanupToTarget(false)">
                清理到目标
              </Button>
            </div>
          </div>
        </ModalBody>

        <ModalFooter align="between" compact>
          <Button size="sm" variant="ghost" :disabled="isStorageBusy" @click="refreshStorageStats">
            {{ isStorageBusy ? '处理中...' : '刷新统计' }}
          </Button>
          <div class="gallery-storage-actions">
            <Button size="sm" variant="outline" :disabled="isStorageBusy" @click="handleCompressStorage">
              压缩图片
            </Button>
            <Button size="sm" variant="outline" :disabled="isStorageBusy" @click="handleCleanupExpired">
              清理过期
            </Button>
          </div>
        </ModalFooter>
      </div>
    </ModalShell>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import {
  galleryApi,
  resolveGalleryFileUrl,
  type GalleryFile,
  type ImageStorageStats,
} from '@/api/gallery'
import { Button, Checkbox, Input } from 'nanocat-ui'
import ActionRow from '@/components/ai/ActionRow.vue'
import DateRangeInputs from '@/components/ai/DateRangeInputs.vue'
import FilterToolbar from '@/components/ai/FilterToolbar.vue'
import GalleryImageCard from '@/components/ai/GalleryImageCard.vue'
import ListPagination from '@/components/ai/ListPagination.vue'
import MetricStrip from '@/components/ai/MetricStrip.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import SelectionBulkBar from '@/components/ai/SelectionBulkBar.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import { downloadUrlAsFile, saveBlob } from '@/lib/downloads'
import { getNumberPreference, preferenceKeys, setNumberPreference } from '@/lib/preferences'

const GalleryLightbox = defineAsyncComponent(() => import('@/components/ai/GalleryLightbox.vue'))
const GalleryTagEditorModal = defineAsyncComponent(() => import('@/components/ai/GalleryTagEditorModal.vue'))
const OperationProgressModal = defineAsyncComponent(() => import('@/components/ai/OperationProgressModal.vue'))

const toast = useToast()
const confirmDialog = useConfirmDialog()

const files = ref<GalleryFile[]>([])
const totalSize = ref(0)
const totalItems = ref(0)
const isLoading = ref(true)
const hasLoadedOnce = ref(false)
const galleryLoadError = ref('')
const batchBusy = ref(false)
const isTagSaving = ref(false)
const previewFile = ref<GalleryFile | null>(null)
const tagEditorFile = ref<GalleryFile | null>(null)
const tagDraft = ref('')
const copiedFileKey = ref('')
const tagFilter = ref('all')
const searchQuery = ref('')
const startDate = ref('')
const endDate = ref('')
const galleryPageSizeOptions = [24, 48, 96] as const
const pageSize = ref(getNumberPreference(preferenceKeys.galleryPageSize, 24, { allowed: galleryPageSizeOptions }))
const currentPage = ref(1)
const pageCount = ref(1)
const counts = ref({ all: 0, image: 0, video: 0, music: 0 })
const allTags = ref<string[]>([])
const selectedPaths = ref<Set<string>>(new Set())
const brokenImagePaths = ref<Set<string>>(new Set())
const storageStats = ref<ImageStorageStats | null>(null)
const isStorageModalOpen = ref(false)
const isStorageBusy = ref(false)
const storageActionMessage = ref('')
const storageActionError = ref('')
const targetFreeMb = ref('500')
const operationProgress = reactive({
  open: false,
  title: '',
  subtitle: '',
  total: 0,
  current: 0,
  statusLabel: '已处理',
  message: '',
  error: '',
  busy: false,
})

const tagOptions = computed(() => [
  { label: '全部标签', value: 'all' },
  ...allTags.value.map((tag) => ({ label: tag, value: tag })),
])

const paginationSummary = computed(() => `第 ${currentPage.value} / ${pageCount.value} 页，共 ${totalItems.value} 张`)
const selectedCount = computed(() => selectedPaths.value.size)
const allVisibleSelected = computed(() => files.value.length > 0 && files.value.every((file) => selectedPaths.value.has(file.path)))
const draftTags = computed(() => parseTags(tagDraft.value))
const storageUsagePercent = computed(() => {
  const stats = storageStats.value
  if (!stats || stats.disk_total_mb <= 0) return '-'
  const percent = Math.min(100, Math.max(0, (stats.disk_used_mb / stats.disk_total_mb) * 100))
  return `${percent.toFixed(1)}%`
})
const storageUsageBarWidth = computed(() => (storageUsagePercent.value === '-' ? '0%' : storageUsagePercent.value))
let latestLoadToken = 0
let copyResetTimer: number | null = null
let searchTimer: number | null = null

function getFileUrl(url: string) {
  return resolveGalleryFileUrl(url)
}

async function loadGallery() {
  const loadToken = ++latestLoadToken
  isLoading.value = true
  galleryLoadError.value = ''
  try {
    const [data, tags] = await Promise.all([
      galleryApi.getFiles({
        page: Number(pageSize.value) ? currentPage.value : 1,
        page_size: Number(pageSize.value),
        media_type: 'all',
        tag: tagFilter.value,
        search: searchQuery.value,
        start_date: startDate.value,
        end_date: endDate.value,
      }),
      galleryApi.getTags().catch(() => allTags.value),
    ])
    if (loadToken !== latestLoadToken) return
    files.value = data.files
    totalSize.value = data.total_size
    totalItems.value = data.total
    counts.value = data.counts
    currentPage.value = data.page
    pageCount.value = Math.max(1, data.page_count)
    allTags.value = tags || []
    brokenImagePaths.value = new Set()
    pruneSelection()
    void galleryApi.getStorage()
      .then((storage) => {
        if (loadToken === latestLoadToken) storageStats.value = storage || null
      })
      .catch(() => undefined)
  } catch (error: any) {
    if (loadToken !== latestLoadToken) return
    galleryLoadError.value = error?.message || '加载图片管理失败'
    toast.error(galleryLoadError.value, '加载失败')
  } finally {
    if (loadToken === latestLoadToken) {
      isLoading.value = false
      hasLoadedOnce.value = true
    }
  }
}

async function refreshAll() {
  await loadGallery()
}

async function refreshStorageStats(options: { lock?: boolean } = {}) {
  const shouldLock = options.lock !== false
  if (shouldLock) isStorageBusy.value = true
  storageActionError.value = ''
  try {
    storageStats.value = await galleryApi.getStorage()
  } catch (error: any) {
    storageActionError.value = error?.message || '刷新存储统计失败'
    toast.error(storageActionError.value, '刷新失败')
  } finally {
    if (shouldLock) isStorageBusy.value = false
  }
}

function openStorageModal() {
  isStorageModalOpen.value = true
  storageActionMessage.value = ''
  storageActionError.value = ''
  void refreshStorageStats()
}

function closeStorageModal() {
  if (isStorageBusy.value) return
  isStorageModalOpen.value = false
}

async function handleCompressStorage() {
  const confirmed = await confirmDialog.ask({
    title: '压缩图片',
    message: '将尝试压缩本地图片以释放空间。该操作可能需要一点时间，确定继续吗？',
    confirmText: '开始压缩',
    cancelText: '取消',
  })
  if (!confirmed) return

  isStorageBusy.value = true
  storageActionMessage.value = '正在压缩图片...'
  storageActionError.value = ''
  try {
    const result = await galleryApi.compressStorage()
    storageActionMessage.value = `压缩完成：处理 ${Number(result.compressed || 0)} 张，节省 ${formatSize(Number(result.saved_bytes || 0))}。`
    toast.success(storageActionMessage.value, '压缩完成')
    await Promise.all([refreshStorageStats({ lock: false }), loadGallery()])
  } catch (error: any) {
    storageActionError.value = error?.message || '压缩图片失败'
    toast.error(storageActionError.value, '压缩失败')
  } finally {
    isStorageBusy.value = false
  }
}

async function handleCleanupExpired() {
  const confirmed = await confirmDialog.ask({
    title: '清理过期图片',
    message: '将删除图库中已过期的图片记录和文件。此操作不可恢复，确定继续吗？',
    confirmText: '清理过期',
    cancelText: '取消',
  })
  if (!confirmed) return

  isStorageBusy.value = true
  storageActionMessage.value = '正在清理过期图片...'
  storageActionError.value = ''
  try {
    const result = await galleryApi.cleanupExpired()
    storageActionMessage.value = result.message || `已清理 ${Number(result.deleted || 0)} 张过期图片。`
    toast.success(storageActionMessage.value, '清理完成')
    await Promise.all([refreshStorageStats({ lock: false }), loadGallery()])
  } catch (error: any) {
    storageActionError.value = error?.message || '清理过期图片失败'
    toast.error(storageActionError.value, '清理失败')
  } finally {
    isStorageBusy.value = false
  }
}

async function handleCleanupToTarget(dryRun: boolean) {
  const target = Number(targetFreeMb.value)
  if (!Number.isFinite(target) || target < 1) {
    storageActionError.value = '请输入有效的目标剩余空间。'
    toast.error(storageActionError.value, '参数错误')
    return
  }

  const normalizedTarget = Math.floor(target)
  if (!dryRun) {
    const confirmed = await confirmDialog.ask({
      title: '清理到目标空间',
      message: `将从旧图片开始清理，直到磁盘剩余空间尽量达到 ${formatMb(normalizedTarget)}。此操作不可恢复，确定继续吗？`,
      confirmText: '开始清理',
      cancelText: '取消',
    })
    if (!confirmed) return
  }

  isStorageBusy.value = true
  storageActionMessage.value = dryRun ? '正在预估可清理图片...' : '正在清理到目标剩余空间...'
  storageActionError.value = ''
  try {
    const result = await galleryApi.cleanupToTarget(normalizedTarget, dryRun)
    const removed = Number(result.removed || 0)
    const freedLabel = formatMb(Number(result.freed_mb || 0))
    const currentLabel = formatMb(Number(result.current_free_mb || 0))
    const targetLabel = formatMb(Number(result.target_free_mb || normalizedTarget))
    if (dryRun) {
      storageActionMessage.value = removed > 0
        ? `预估会清理 ${removed} 张，预计释放 ${freedLabel}。当前剩余 ${currentLabel} / 目标 ${targetLabel}。`
        : `无需清理：当前剩余 ${currentLabel}，已达到目标 ${targetLabel}。`
      toast.success(storageActionMessage.value, '预估完成')
      await refreshStorageStats({ lock: false })
    } else {
      storageActionMessage.value = removed > 0
        ? `已清理 ${removed} 张，释放 ${freedLabel}。当前剩余 ${currentLabel} / 目标 ${targetLabel}。`
        : `没有需要清理的图片。当前剩余 ${currentLabel} / 目标 ${targetLabel}。`
      toast.success(storageActionMessage.value, '清理完成')
      await Promise.all([refreshStorageStats({ lock: false }), loadGallery()])
    }
  } catch (error: any) {
    storageActionError.value = error?.message || '按目标剩余空间清理失败'
    toast.error(storageActionError.value, '清理失败')
  } finally {
    isStorageBusy.value = false
  }
}

function resetAndLoad() {
  if (currentPage.value !== 1) {
    currentPage.value = 1
    return
  }
  void loadGallery()
}

async function handleDelete(file: GalleryFile) {
  const confirmed = await confirmDialog.ask({
    title: '确认删除',
    message: `确定要删除 ${file.filename} 吗？此操作不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '删除图片'
  operationProgress.subtitle = file.filename
  operationProgress.total = 1
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在提交删除请求...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    await galleryApi.deleteFile(file.path)
    operationProgress.current = 1
    operationProgress.statusLabel = '已处理'
    operationProgress.message = '删除完成，正在刷新列表...'
    selectedPaths.value.delete(file.path)
    selectedPaths.value = new Set(selectedPaths.value)
    if (previewFile.value?.path === file.path) closePreview()
    if (tagEditorFile.value?.path === file.path) closeTagEditor()
    if (files.value.length === 1 && currentPage.value > 1) {
      currentPage.value -= 1
    } else {
      await loadGallery()
    }
    toast.success(`已删除 ${file.filename}`, '删除成功')
    operationProgress.message = '图片已删除'
  } catch (error: any) {
    operationProgress.error = error?.message || '删除图片失败'
    toast.error(operationProgress.error, '删除失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function handleDeleteSelected() {
  const paths = Array.from(selectedPaths.value)
  if (!paths.length) return
  const confirmed = await confirmDialog.ask({
    title: '批量删除',
    message: `确定要删除已选择的 ${paths.length} 张图片吗？此操作不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '批量删除图片'
  operationProgress.subtitle = `已选择 ${paths.length} 张`
  operationProgress.total = paths.length
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在提交批量删除请求...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    const result = await galleryApi.deleteFiles(paths)
    operationProgress.current = Number(result.removed || 0)
    operationProgress.statusLabel = '已处理'
    operationProgress.message = '删除完成，正在刷新列表...'
    clearSelection()
    await loadGallery()
    toast.success(`已删除 ${Number(result.removed || 0)} 张图片。`, '删除成功')
    operationProgress.message = `已删除 ${Number(result.removed || 0)} 张图片`
  } catch (error: any) {
    operationProgress.error = error?.message || '批量删除失败'
    toast.error(operationProgress.error, '删除失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function handleBatchDownload() {
  const paths = Array.from(selectedPaths.value)
  if (!paths.length) return
  batchBusy.value = true
  operationProgress.open = true
  operationProgress.title = '批量下载图片'
  operationProgress.subtitle = `已选择 ${paths.length} 张`
  operationProgress.total = paths.length
  operationProgress.current = 0
  operationProgress.statusLabel = '已提交'
  operationProgress.message = '正在打包 ZIP...'
  operationProgress.error = ''
  operationProgress.busy = true
  try {
    const blob = await galleryApi.downloadZip(paths)
    operationProgress.current = paths.length
    operationProgress.statusLabel = '已处理'
    operationProgress.message = 'ZIP 已生成，正在启动下载...'
    saveBlob(blob, `images_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.zip`)
    toast.success(`已打包 ${paths.length} 张图片。`, '下载已开始')
    operationProgress.message = `已打包 ${paths.length} 张图片`
  } catch (error: any) {
    operationProgress.error = error?.message || '批量下载失败'
    toast.error(operationProgress.error, '下载失败')
  } finally {
    batchBusy.value = false
    operationProgress.busy = false
  }
}

async function downloadFile(file: GalleryFile) {
  try {
    await downloadUrlAsFile(getFileUrl(file.url), file.filename, { localPath: file.path })
    toast.success(`已开始下载 ${file.filename}`)
  } catch (error: any) {
    toast.error(error?.message || '无法读取图片文件', '下载失败')
  }
}

async function copyFileLink(file: GalleryFile | null) {
  if (!file) return
  const url = getFileUrl(file.url)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
    } else {
      const input = document.createElement('input')
      input.value = url
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
    }
    copiedFileKey.value = file.path
    if (copyResetTimer !== null) {
      window.clearTimeout(copyResetTimer)
    }
    copyResetTimer = window.setTimeout(() => {
      copiedFileKey.value = ''
      copyResetTimer = null
    }, 1800)
    toast.success('图片链接已复制。', '复制成功')
  } catch {
    copiedFileKey.value = ''
    toast.error('复制链接失败。', '复制失败')
  }
}

function openPreview(file: GalleryFile) {
  previewFile.value = file
}

function closePreview() {
  previewFile.value = null
}

function openTagEditor(file: GalleryFile) {
  tagEditorFile.value = file
  tagDraft.value = file.tags.join(', ')
}

function closeTagEditor() {
  if (isTagSaving.value) return
  tagEditorFile.value = null
  tagDraft.value = ''
}

async function saveTagEditor() {
  const file = tagEditorFile.value
  if (!file) return
  const tags = draftTags.value
  isTagSaving.value = true
  try {
    const result = await galleryApi.updateTags(file.path, tags)
    applyFileTags(file.path, result.tags || tags)
    allTags.value = await galleryApi.getTags()
    if (tagFilter.value !== 'all' && !(result.tags || tags).includes(tagFilter.value)) {
      await loadGallery()
    }
    toast.success('标签已保存。', '保存成功')
    closeTagEditor()
  } catch (error: any) {
    toast.error(error?.message || '保存标签失败', '保存失败')
  } finally {
    isTagSaving.value = false
  }
}

function applyFileTags(path: string, tags: string[]) {
  files.value = files.value.map((file) => (file.path === path ? { ...file, tags } : file))
  if (previewFile.value?.path === path) previewFile.value = { ...previewFile.value, tags }
  if (tagEditorFile.value?.path === path) tagEditorFile.value = { ...tagEditorFile.value, tags }
}

function parseTags(value: string) {
  return Array.from(new Set(value.split(/[,\s，、]+/).map((tag) => tag.trim()).filter(Boolean)))
}

function toggleDraftTag(tag: string) {
  const next = new Set(draftTags.value)
  if (next.has(tag)) {
    next.delete(tag)
  } else {
    next.add(tag)
  }
  tagDraft.value = Array.from(next).join(', ')
}

function setTagFilter(tag: string) {
  tagFilter.value = tag
  resetAndLoad()
}

function toggleSelect(path: string, checked?: boolean) {
  const next = new Set(selectedPaths.value)
  const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(path)
  if (shouldSelect) {
    next.add(path)
  } else {
    next.delete(path)
  }
  selectedPaths.value = next
}

function toggleSelectAllVisible(checked?: boolean) {
  const next = new Set(selectedPaths.value)
  const shouldSelect = typeof checked === 'boolean' ? checked : !allVisibleSelected.value
  for (const file of files.value) {
    if (shouldSelect) next.add(file.path)
    else next.delete(file.path)
  }
  selectedPaths.value = next
}

function isSelected(path: string) {
  return selectedPaths.value.has(path)
}

function clearSelection() {
  selectedPaths.value = new Set()
}

function pruneSelection() {
  if (selectedPaths.value.size === 0) return
  const loadedPaths = new Set(files.value.map((file) => file.path))
  const next = new Set(Array.from(selectedPaths.value).filter((path) => loadedPaths.has(path)))
  selectedPaths.value = next
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatMb(value: number): string {
  return formatSize(Number(value || 0) * 1024 * 1024)
}

function formatTimeRemaining(seconds: number): string {
  if (seconds <= 0) return '已过期'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}天 ${h}小时`
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function formatDimensions(file: GalleryFile): string {
  return file.width && file.height ? `${file.width}x${file.height}` : ''
}

function storageLabel(file: GalleryFile): string {
  if (file.storage === 'both') return '本地+云'
  if (file.storage === 'webdav') return '云端'
  return '本地'
}

function canPreviewFile(file: GalleryFile): boolean {
  return file.size > 128 && !brokenImagePaths.value.has(file.path)
}

function handleImageError(event: Event, path: string) {
  const img = event.target as HTMLImageElement
  img.style.opacity = '0'
  brokenImagePaths.value = new Set([...brokenImagePaths.value, path])
}

watch([tagFilter, startDate, endDate, pageSize], () => {
  resetAndLoad()
})
const galleryMetricItems = computed(() => [
  { label: '当前视图', value: totalItems.value, icon: 'lucide:image', iconClass: 'text-cyan-600', iconBgClass: 'bg-transparent' },
  { label: '图库总量', value: storageStats.value ? storageStats.value.image_count : counts.value.all, icon: 'lucide:archive', iconClass: 'text-violet-600', iconBgClass: 'bg-transparent' },
  { label: '当前占用', value: formatSize(totalSize.value), icon: 'lucide:database', iconClass: 'text-emerald-600', iconBgClass: 'bg-transparent' },
  { label: '磁盘剩余', value: storageStats.value ? formatSize(storageStats.value.disk_free_mb * 1024 * 1024) : '-', icon: 'lucide:hard-drive', iconClass: 'text-amber-600', iconBgClass: 'bg-transparent' },
])

watch(pageSize, (value) => {
  setNumberPreference(preferenceKeys.galleryPageSize, value)
})

watch(searchQuery, () => {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
  }
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    resetAndLoad()
  }, 250)
})

watch(currentPage, () => {
  void loadGallery()
})

onMounted(() => {
  void loadGallery()
})

onBeforeUnmount(() => {
  if (copyResetTimer !== null) {
    window.clearTimeout(copyResetTimer)
    copyResetTimer = null
  }
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
    searchTimer = null
  }
})
</script>

<style scoped>
.gallery-page {
  --gallery-radius: 16px;

  display: flex;
  flex-direction: column;
  gap: 16px;
}

.gallery-hero {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px;
}

:deep(.gallery-filter-search) {
  flex: 1 1 15rem;
  min-width: min(100%, 14rem);
}

.gallery-filter-field {
  flex: 0 0 9rem;
  min-width: 8rem;
}

.gallery-filter-field--tag {
  flex-basis: 9rem;
}

.gallery-date-range {
  --date-range-flex: 0 1 17rem;
  --date-range-min-width: min(100%, 16rem);
  --date-range-input-min-width: 7.25rem;
}

@media (max-width: 640px) {
  .gallery-hero {
    padding: 14px;
  }

  :deep(.gallery-filter-search),
  .gallery-date-range,
  .gallery-filter-field {
    flex: 1 1 auto;
    min-width: 0;
    width: 100%;
  }
}

.gallery-content-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid hsl(var(--border));
  background: hsl(var(--card));
}

.gallery-state-block {
  min-height: 320px;
  border: 0;
  border-radius: 0;
}

.gallery-storage-modal {
  background: hsl(var(--card));
}

.gallery-storage-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid hsl(var(--border));
  padding: 16px 20px 14px;
}

.gallery-storage-header h3 {
  margin-top: 4px;
  color: hsl(var(--foreground));
  font-size: 1.05rem;
  font-weight: 700;
}

.gallery-storage-header p:last-child {
  margin-top: 4px;
  color: hsl(var(--muted-foreground));
  font-size: 0.8125rem;
}

.gallery-storage-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.gallery-storage-alert.is-error {
  border: 1px solid rgb(244 63 94 / 0.28);
  background: rgb(244 63 94 / 0.08);
  color: rgb(190 18 60);
}

.gallery-storage-alert.is-success {
  border: 1px solid rgb(16 185 129 / 0.24);
  background: rgb(16 185 129 / 0.08);
  color: rgb(4 120 87);
}

.gallery-storage-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.gallery-storage-card {
  min-width: 0;
  border: 1px solid hsl(var(--border));
  border-radius: 14px;
  background: hsl(var(--muted) / 0.24);
  padding: 12px;
}

.gallery-storage-card span,
.gallery-storage-summary span {
  display: block;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.gallery-storage-card strong,
.gallery-storage-summary strong {
  display: block;
  margin-top: 4px;
  color: hsl(var(--foreground));
  font-size: 1rem;
  font-weight: 700;
}

.gallery-storage-meter {
  margin-top: 14px;
  border: 1px solid hsl(var(--border));
  border-radius: 14px;
  padding: 12px;
}

.gallery-storage-meter__bar {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: hsl(var(--muted));
}

.gallery-storage-meter__bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, hsl(var(--primary)), rgb(20 184 166));
  transition: width 0.2s ease;
}

.gallery-storage-meter__meta,
.gallery-storage-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.gallery-storage-meter__meta {
  margin-top: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.gallery-storage-meter__meta strong {
  color: hsl(var(--foreground));
}

.gallery-storage-summary {
  margin-top: 12px;
  border-radius: 14px;
  background: hsl(var(--secondary) / 0.42);
  padding: 12px;
}

.gallery-storage-target {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 7.5rem auto;
  align-items: end;
  gap: 10px;
  margin-top: 12px;
  border: 1px dashed hsl(var(--border));
  border-radius: 14px;
  background: hsl(var(--muted) / 0.18);
  padding: 12px;
}

.gallery-storage-target span {
  display: block;
  color: hsl(var(--foreground));
  font-size: 0.8125rem;
  font-weight: 700;
}

.gallery-storage-target p {
  margin-top: 4px;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  line-height: 1.45;
}

:deep(.gallery-storage-target-input) {
  min-width: 0;
}

.gallery-storage-target-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.gallery-storage-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 12px;
}

@media (min-width: 1280px) {
  .image-grid {
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  }
}

@media (max-width: 640px) {
  .gallery-content-toolbar {
    align-items: stretch;
    border-radius: var(--gallery-radius);
  }

  .gallery-storage-grid {
    grid-template-columns: 1fr;
  }

  .gallery-storage-summary {
    flex-direction: column;
    align-items: stretch;
  }

  .gallery-storage-target {
    grid-template-columns: 1fr;
  }

  .gallery-storage-target-actions {
    justify-content: stretch;
  }

  .gallery-storage-target-actions > * {
    flex: 1 1 auto;
  }

  .gallery-storage-actions {
    width: 100%;
  }

  .gallery-storage-actions > * {
    flex: 1 1 auto;
  }

}

@media (max-width: 420px) {
  .image-grid {
    grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
  }
}
</style>
