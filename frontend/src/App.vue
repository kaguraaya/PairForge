<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, jsonBody } from './api/client'
import type { BatchProgress, Estimate, ImageAsset, ImportPreview, ModelInfo, Project, ProviderCredential, ProviderProfile, Question, QuotaStatus, SystemInfo } from './api/types'
import { candidateDefaults, candidateLimits, sizePresets } from './domain/generation'
import { isExportPending } from './domain/export'
import { statusLabel, statusTone } from './domain/status'
import { initialTheme, oppositeTheme, THEME_STORAGE_KEY, type ColorTheme } from './domain/theme'

type Section = 'projects' | 'import' | 'workbench' | 'settings' | 'exports' | 'about'

const section = ref<Section>('projects')
const busy = ref(false)
const projects = ref<Project[]>([])
const project = ref<Project | null>(null)
const questions = ref<Question[]>([])
const profiles = ref<ProviderProfile[]>([])
const models = ref<ModelInfo[]>([])
const currentQuestionId = ref('')
const search = ref('')
const preview = ref<ImportPreview | null>(null)
const importProjectName = ref('日漫 ACG 题库')
const importDragging = ref(false)
const rangeVisible = ref(false)
const rangeEstimate = ref<Estimate | null>(null)
const rangePreflight = ref<QuotaStatus | null>(null)
const rangeCalculating = ref(false)
const settingsPreflight = ref<QuotaStatus | null>(null)
const batchProgress = ref<BatchProgress | null>(null)
const activeBatchId = ref('')
const batchActionBusy = ref(false)
const cacheBusy = ref(false)
const systemInfo = ref<SystemInfo | null>(null)
const clock = ref(Date.now())
const theme = ref<ColorTheme>(initialTheme(
  window.localStorage.getItem(THEME_STORAGE_KEY),
  window.matchMedia('(prefers-color-scheme: dark)').matches,
))
const range = reactive({ start_code: '001', end_code: '100', q1_outputs: 2, q2_outputs: 1, singleOnly: true, parallelism: 8 })
const exported = ref<{ directory: string; images_directory: string; question_count: number; image_count: number } | null>(null)

const profileForm = reactive({
  id: '', provider: 'volcengine', display_name: 'Seedream 5.0 Lite',
  base_url: 'https://ark.cn-beijing.volces.com', workspace_id: '',
  model_id: 'doubao-seedream-5-0-lite-260128', api_key: '', remember_secret: true,
  api_mode: 'standard',
  max_outputs: 4, default_size: '1024x1024', unit_price_cny: 0,
  size: '2048x2048', watermark: false, seed: undefined as number | undefined,
  guidance_scale: undefined as number | undefined, prompt_extend: false, thinking_mode: true,
  single_output_default: true, default_q1_outputs: 2, default_q2_outputs: 1,
})
const credentialForm = reactive({
  id: '',
  label: '备用 Key', account_label: '', priority: 20, api_key: '',
  remember_secret: true, manual_remaining_images: undefined as number | undefined,
})

const nav: Array<{ key: Section; code: string; label: string }> = [
  { key: 'projects', code: '00', label: '项目' },
  { key: 'import', code: '01', label: '导入' },
  { key: 'workbench', code: '02', label: '工作台' },
  { key: 'settings', code: '03', label: '设置' },
  { key: 'exports', code: '04', label: '成品' },
  { key: 'about', code: '05', label: '关于' },
]

const currentQuestion = computed(() => questions.value.find(q => q.id === currentQuestionId.value) || questions.value[0])
const visibleQuestions = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return questions.value.filter(q => !needle || `${q.code}${q.title}${q.answer}`.toLowerCase().includes(needle))
})
const currentProfile = computed(() => profiles.value.find(p => p.id === project.value?.selected_provider_profile_id) || profiles.value[0])
const editingProfile = computed(() => profiles.value.find(p => p.id === profileForm.id))
const formModel = computed(() => models.value.find(item => (
  item.provider === profileForm.provider && item.model === profileForm.model_id
)))
const formLimits = computed(() => profileForm.provider === 'custom'
  ? { image1: Math.max(1, profileForm.max_outputs), image2: Math.max(1, profileForm.max_outputs) }
  : candidateLimits(formModel.value))
const formSizePresets = computed(() => sizePresets(formModel.value))
const credentialRows = computed(() => {
  const checked = settingsPreflight.value
  if (checked && checked.profile_id === editingProfile.value?.id) return checked.credentials
  return editingProfile.value?.credentials || []
})
const rangeModel = computed(() => models.value.find(item => (
  item.provider === currentProfile.value?.provider && item.model === currentProfile.value?.model_id
)))
const rangeLimits = computed(() => candidateLimits(rangeModel.value))
const rangeSlider = computed<number[]>({
  get() {
    const start = questions.value.findIndex(item => item.code === range.start_code)
    const end = questions.value.findIndex(item => item.code === range.end_code)
    return [start >= 0 ? start + 1 : 1, end >= 0 ? end + 1 : Math.max(1, questions.value.length)]
  },
  set(value) {
    const last = Math.max(1, questions.value.length)
    const start = Math.max(1, Math.min(Math.round(value[0] || 1), last))
    const end = Math.max(start, Math.min(Math.round(value[1] || start), last))
    range.start_code = questions.value[start - 1]?.code || range.start_code
    range.end_code = questions.value[end - 1]?.code || range.end_code
  },
})
const rangeStartQuestion = computed(() => questions.value[rangeSlider.value[0] - 1])
const rangeEndQuestion = computed(() => questions.value[rangeSlider.value[1] - 1])
const rangeQuestionCount = computed(() => Math.max(0, rangeSlider.value[1] - rangeSlider.value[0] + 1))
const rangeMarks = computed(() => {
  const last = Math.max(1, questions.value.length)
  return last === 1 ? { 1: '第 1 题' } : { 1: '第 1 题', [last]: `第 ${last} 题` }
})
const isSeedream = computed(() => profileForm.provider === 'volcengine')
const effectiveVolcengineEndpoint = computed(() => {
  const host = profileForm.base_url.replace(/\/+$/, '')
  const path = profileForm.api_mode === 'agent_plan'
    ? '/api/plan/v3/images/generations'
    : '/api/v3/images/generations'
  return `${host}${path}`
})
const activeApiKeyUrl = computed(() => (
  isSeedream.value && profileForm.api_mode === 'agent_plan'
    ? formModel.value?.agent_plan_api_key_url
    : formModel.value?.api_key_url
))
const activeDocumentationUrl = computed(() => (
  isSeedream.value && profileForm.api_mode === 'agent_plan'
    ? formModel.value?.agent_plan_documentation_url
    : formModel.value?.documentation_url
))
const customGuidance = computed({
  get: () => profileForm.guidance_scale != null,
  set: (enabled: boolean) => { profileForm.guidance_scale = enabled ? 5.5 : undefined },
})
const isQwen = computed(() => profileForm.provider === 'alibaba' && profileForm.model_id.startsWith('qwen-image'))
const isWan = computed(() => profileForm.provider === 'alibaba' && profileForm.model_id.startsWith('wan'))
const q1Assets = computed(() => currentQuestion.value?.assets.filter(a => a.stage === 'image1') || [])
const q2Assets = computed(() => currentQuestion.value?.assets.filter(a => a.stage === 'image2') || [])
const selectedImage1 = computed(() => currentQuestion.value?.assets.find(a => a.id === currentQuestion.value?.selected_image1_id))
const selectedImage2 = computed(() => currentQuestion.value?.assets.find(a => a.id === currentQuestion.value?.selected_image2_id))
const completedCount = computed(() => questions.value.filter(q => q.state === 'completed').length)
const exportPendingCount = computed(() => questions.value.filter(isExportPending).length)
const finalPrompt1 = computed(() => joinPrompt(currentQuestion.value?.image1_prompt, project.value?.q1_prompt_suffix))
const finalPrompt2 = computed(() => joinPrompt(currentQuestion.value?.image2_prompt, project.value?.q2_prompt_suffix))
const guidanceMarks = { 1: '更自由', 5.5: '平衡', 10: '更严格' }
const parallelismMarks = { 1: '1', 4: '4', 8: '推荐 8', 12: '12' }
const batchStatusLabels: Record<string, string> = {
  running: '批量生成中', waiting_review: '等待选择候选图', completed: '本批已完成',
  partial: '部分完成', failed: '本批生成失败', paused: '已暂停', cancelled: '已取消',
}
const batchStatusText = computed(() => batchStatusLabels[batchProgress.value?.status || ''] || '准备中')
const retryCountdown = computed(() => {
  const retryAt = batchProgress.value?.next_retry_at
  if (!retryAt) return ''
  const seconds = Math.max(0, Math.ceil((new Date(retryAt).getTime() - clock.value) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`
})
const effectiveBatchStatusText = computed(() => (
  batchProgress.value?.retry_waiting_count
    ? `限流冷却中，约 ${retryCountdown.value || '稍后'}自动继续`
    : batchStatusText.value
))
const themeActionLabel = computed(() => theme.value === 'dark' ? '切换亮色' : '切换暗夜')
const failureAdvice = computed(() => {
  switch (currentQuestion.value?.latest_error_category) {
    case 'authentication':
      return '请到设置页检查 Key，确认它未被撤销、复制时没有多余空格，并核对 API 地址；基础连通检查不能代替真实鉴权。'
    case 'quota':
      return '该 Key 的余额或调用额度不足。请到厂商控制台核对余额，或启用另一条备用 Key。'
    case 'rate_limit':
      return '请求频率超过厂商限制。稍后再试，或降低并发、增加可用 Key。'
    case 'safety':
      return '提示词或参考图触发了厂商内容安全策略。请检查本题最终提示词和已选图一后再重试。'
    case 'invalid_request':
      return `基础网络连通不等于 Key 或模型可用。请先确认 ${currentProfile.value?.display_name || '当前模型'} 已在厂商控制台开通，再核对 Key、模型 ID、尺寸与专属参数。旧版本没有保存厂商错误码；用新版重试后会显示具体代码。`
    default:
      return '请先检查模型设置和 Key 状态。新版会保留脱敏后的厂商错误码与请求 ID，便于继续定位。'
  }
})

watch(
  () => [range.start_code, range.end_code, range.q1_outputs, range.q2_outputs, range.singleOnly, range.parallelism],
  () => {
    rangeEstimate.value = null
    rangePreflight.value = null
  },
)

watch(theme, (value) => {
  document.documentElement.dataset.theme = value
  document.documentElement.classList.toggle('dark', value === 'dark')
  window.localStorage.setItem(THEME_STORAGE_KEY, value)
}, { immediate: true })

function joinPrompt(original = '', suffix = '') {
  return suffix.trim() ? `${original}\n\n【全局补充要求】\n${suffix.trim()}` : original
}

function showError(error: unknown) {
  ElMessage.error(error instanceof Error ? error.message : '操作失败')
}

async function refreshProjects() {
  projects.value = await api<Project[]>('/projects')
}

async function chooseProject(id: string, target: Section = 'workbench') {
  exported.value = null
  project.value = await api<Project>(`/projects/${id}`)
  profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${id}`)
  const selectedProfile = profiles.value.find(
    item => item.id === project.value?.selected_provider_profile_id,
  ) || profiles.value[0]
  if (selectedProfile) editProfile(selectedProfile)
  questions.value = await api<Question[]>(`/projects/${id}/questions`)
  activeBatchId.value = ''
  await refreshBatchProgress()
  currentQuestionId.value ||= questions.value[0]?.id || ''
  if (!questions.value.some(q => q.id === currentQuestionId.value)) currentQuestionId.value = questions.value[0]?.id || ''
  section.value = target
}

async function pollQuestions() {
  if (!project.value || section.value !== 'workbench') return
  try { questions.value = await api<Question[]>(`/projects/${project.value.id}/questions`) } catch { /* next poll retries */ }
  try { await refreshBatchProgress() } catch { /* next poll retries */ }
}

async function refreshBatchProgress() {
  if (!project.value) return
  const endpoint = activeBatchId.value
    ? `/generation/batches/${activeBatchId.value}`
    : `/generation/projects/${project.value.id}/latest-batch`
  const progress = await api<BatchProgress | null>(endpoint)
  batchProgress.value = progress
  activeBatchId.value = progress?.id || ''
}

function toggleTheme() {
  theme.value = oppositeTheme(theme.value)
}

function formatBytes(value = 0) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}

async function refreshSystemInfo() {
  systemInfo.value = await api<SystemInfo>('/system/info')
}

async function clearCache() {
  if (cacheBusy.value) return
  try {
    await ElMessageBox.confirm(
      '只会删除导入预览和格式转换等临时文件，不会删除题库数据库、候选图或导出成品。',
      '确认清除临时缓存？',
      { confirmButtonText: '清除缓存', cancelButtonText: '保留', type: 'warning' },
    )
  } catch { return }
  cacheBusy.value = true
  try {
    const result = await api<{ cleared_file_count: number; cleared_bytes: number }>(
      '/system/cache/clear', { method: 'POST' },
    )
    await refreshSystemInfo()
    ElMessage.success(`已清除 ${result.cleared_file_count} 个临时文件（${formatBytes(result.cleared_bytes)}）`)
  } catch (error) { showError(error) } finally { cacheBusy.value = false }
}

async function pauseBatch() {
  if (!batchProgress.value?.can_pause || batchActionBusy.value) return
  batchActionBusy.value = true
  try {
    batchProgress.value = await api<BatchProgress>(
      `/generation/batches/${batchProgress.value.id}/pause`,
      { method: 'POST' },
    )
    ElMessage.success('已安全暂停：不再发出新请求，在途结果仍会保存。')
  } catch (error) { showError(error) } finally { batchActionBusy.value = false }
}

async function resumeBatch() {
  if (!batchProgress.value?.can_resume || batchActionBusy.value) return
  batchActionBusy.value = true
  try {
    batchProgress.value = await api<BatchProgress>(
      `/generation/batches/${batchProgress.value.id}/resume`,
      { method: 'POST' },
    )
    ElMessage.success('已从暂停位置继续生成。')
  } catch (error) { showError(error) } finally { batchActionBusy.value = false }
}

async function upload(file: File) {
  busy.value = true
  preview.value = null
  try {
    const data = new FormData()
    data.append('file', file)
    preview.value = await api<ImportPreview>('/imports/preview', { method: 'POST', body: data })
    importProjectName.value = file.name.replace(/\.(docx?|md|markdown)$/i, '')
  } catch (error) { showError(error) } finally { busy.value = false }
}

function onFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) upload(file)
}

function onDrop(event: DragEvent) {
  importDragging.value = false
  const file = event.dataTransfer?.files[0]
  if (file) upload(file)
}

async function confirmImport() {
  if (!preview.value || preview.value.error_count) return
  busy.value = true
  try {
    const result = await api<{ project_id: string }>('/imports/confirm', jsonBody({
      token: preview.value.token, project_name: importProjectName.value,
    }))
    await refreshProjects()
    await chooseProject(result.project_id, 'settings')
    ElMessage.success('题库已导入。下一步配置生图服务。')
  } catch (error) { showError(error) } finally { busy.value = false }
}

function chooseModel(modelId: string) {
  const model = models.value.find(item => item.model === modelId)
  if (!model) return
  profileForm.provider = model.provider
  profileForm.display_name = model.display_name
  profileForm.base_url = model.provider === 'volcengine'
    ? 'https://ark.cn-beijing.volces.com'
    : 'https://dashscope.aliyuncs.com'
  profileForm.size = model.default_size
  const limits = candidateLimits(model)
  profileForm.default_q1_outputs = Math.min(profileForm.default_q1_outputs, limits.image1)
  profileForm.default_q2_outputs = Math.min(profileForm.default_q2_outputs, limits.image2)
}

function editProfile(profile: ProviderProfile) {
  Object.assign(profileForm, {
    id: profile.id, provider: profile.provider, display_name: profile.display_name,
    base_url: profile.base_url, workspace_id: profile.workspace_id || '', model_id: profile.model_id,
    api_key: '', remember_secret: profile.remember_secret,
    api_mode: profile.config.api_mode === 'agent_plan' ? 'agent_plan' : 'standard',
    max_outputs: Number(profile.config.max_outputs || 4),
    default_size: String(profile.config.default_size || '1024x1024'),
    unit_price_cny: Number(profile.config.unit_price_cny || 0),
    size: String(profile.config.size || models.value.find(item => item.provider === profile.provider && item.model === profile.model_id)?.default_size || '1024x1024'),
    watermark: Boolean(profile.config.watermark ?? false),
    seed: profile.config.seed == null ? undefined : Number(profile.config.seed),
    guidance_scale: profile.config.guidance_scale == null ? undefined : Number(profile.config.guidance_scale),
    prompt_extend: Boolean(profile.config.prompt_extend ?? false),
    thinking_mode: Boolean(profile.config.thinking_mode ?? true),
    single_output_default: Boolean(profile.config.single_output_default ?? true),
    default_q1_outputs: candidateValue(profile.config.default_q1_outputs, 2, profile.provider === 'custom' ? Number(profile.config.max_outputs || 4) : candidateLimits(models.value.find(item => item.provider === profile.provider && item.model === profile.model_id)).image1),
    default_q2_outputs: candidateValue(profile.config.default_q2_outputs, 1, profile.provider === 'custom' ? Number(profile.config.max_outputs || 4) : candidateLimits(models.value.find(item => item.provider === profile.provider && item.model === profile.model_id)).image2),
  })
  settingsPreflight.value = null
  resetCredentialForm()
}

async function chooseSavedProfile(profile: ProviderProfile) {
  editProfile(profile)
  if (!project.value || project.value.selected_provider_profile_id === profile.id) return
  try {
    await api(`/projects/${project.value.id}/provider-profile`, jsonBody({
      profile_id: profile.id,
    }, 'PUT'))
    project.value.selected_provider_profile_id = profile.id
    ElMessage.success(`当前项目已切换到全局服务“${profile.display_name}”`)
  } catch (error) { showError(error) }
}

function credentialStatus(status: string) {
  return ({ active: '可用', cooldown: '冷却中', exhausted: '额度耗尽', invalid: '无效', disabled: '已停用' } as Record<string, string>)[status] || status
}

function candidateValue(value: unknown, fallback: number, maximum: number) {
  const parsed = Number(value ?? fallback)
  return Math.max(1, Math.min(Number.isFinite(parsed) ? Math.round(parsed) : fallback, Math.max(1, maximum)))
}

function credentialProgress(credential: ProviderCredential) {
  if (credential.manual_remaining_images == null) return null
  const used = Number(credential.local_generated_images || 0)
  const total = credential.manual_remaining_images + used
  return total <= 0 ? 0 : Math.round((credential.manual_remaining_images / total) * 100)
}

function scrollSettings(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function inspectCurrentModel() {
  section.value = 'settings'
  nextTick(() => scrollSettings('model-settings'))
}

function resetCredentialForm() {
  Object.assign(credentialForm, {
    id: '', label: '备用 Key', account_label: '', priority: 20, api_key: '',
    remember_secret: true, manual_remaining_images: undefined,
  })
}

function editCredential(credential: ProviderCredential) {
  Object.assign(credentialForm, {
    id: credential.id,
    label: credential.label,
    account_label: credential.account_label || '',
    priority: credential.priority,
    api_key: '',
    remember_secret: credential.remember_secret,
    manual_remaining_images: credential.manual_remaining_images ?? undefined,
  })
  requestAnimationFrame(() => scrollSettings('credential-editor'))
}

function newPresetProfile() {
  const model = models.value.find(item => item.model === 'doubao-seedream-5-0-lite-260128') || models.value[0]
  Object.assign(profileForm, {
    id: '', provider: model?.provider || 'volcengine', display_name: model?.display_name || 'Seedream 5.0 Lite',
    base_url: model?.provider === 'alibaba' ? 'https://dashscope.aliyuncs.com' : 'https://ark.cn-beijing.volces.com',
    workspace_id: '', model_id: model?.model || 'doubao-seedream-5-0-lite-260128', api_key: '', remember_secret: true,
    api_mode: 'standard',
    max_outputs: 4, default_size: '1024x1024', unit_price_cny: 0,
    size: model?.default_size || '2048x2048', watermark: false, seed: undefined,
    guidance_scale: undefined, prompt_extend: false, thinking_mode: true,
    single_output_default: true, default_q1_outputs: Math.min(2, model?.max_text_outputs || 1), default_q2_outputs: 1,
  })
  settingsPreflight.value = null
  resetCredentialForm()
}

function newCustomProfile() {
  Object.assign(profileForm, {
    id: '', provider: 'custom', display_name: '自定义 OpenAI 兼容服务', base_url: '', workspace_id: '',
    model_id: '', api_key: '', remember_secret: true, max_outputs: 4,
    api_mode: 'standard',
    default_size: '1024x1024', unit_price_cny: 0,
    size: '1024x1024', watermark: false, seed: undefined,
    guidance_scale: undefined, prompt_extend: false, thinking_mode: true,
    single_output_default: true, default_q1_outputs: 2, default_q2_outputs: 1,
  })
  settingsPreflight.value = null
  resetCredentialForm()
}

async function saveProfile() {
  if (!project.value) return
  busy.value = true
  try {
    const config: Record<string, unknown> = {
      size: profileForm.size,
      watermark: profileForm.watermark,
      single_output_default: profileForm.single_output_default,
      default_q1_outputs: candidateValue(profileForm.default_q1_outputs, 2, formLimits.value.image1),
      default_q2_outputs: candidateValue(profileForm.default_q2_outputs, 1, formLimits.value.image2),
    }
    if (profileForm.provider === 'custom') Object.assign(config, {
      max_outputs: profileForm.max_outputs,
      default_size: profileForm.default_size,
      unit_price_cny: profileForm.unit_price_cny,
      supports_image_edit: true,
    })
    if (profileForm.provider === 'volcengine') Object.assign(config, {
      api_mode: profileForm.api_mode,
      seed: profileForm.seed ?? null,
      guidance_scale: profileForm.guidance_scale ?? null,
    })
    if (profileForm.provider === 'alibaba' && profileForm.model_id.startsWith('qwen-image')) Object.assign(config, {
      seed: profileForm.seed ?? null,
      prompt_extend: profileForm.prompt_extend,
    })
    if (profileForm.provider === 'alibaba' && profileForm.model_id.startsWith('wan')) Object.assign(config, {
      thinking_mode: profileForm.thinking_mode,
    })
    const saved = await api<ProviderProfile>('/settings/profiles', jsonBody({
      ...profileForm, id: profileForm.id || null, project_id: project.value.id, config,
      api_key: profileForm.api_key || null,
    }))
    project.value = await api<Project>(`/projects/${project.value.id}`)
    profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${project.value.id}`)
    editProfile(profiles.value.find(item => item.id === saved.id) || saved)
    ElMessage.success(saved.session_only ? '配置已保存；密钥仅在本次运行中保留' : '生图服务配置已保存')
  } catch (error) { showError(error) } finally { busy.value = false }
}

async function addCredential() {
  if (!profileForm.id || (!credentialForm.id && !credentialForm.api_key)) return
  busy.value = true
  try {
    await api(`/settings/profiles/${profileForm.id}/credentials`, jsonBody({
      ...credentialForm,
      manual_remaining_images: credentialForm.manual_remaining_images ?? null,
    }))
    profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${project.value?.id}`)
    const edited = Boolean(credentialForm.id)
    settingsPreflight.value = null
    resetCredentialForm()
    ElMessage.success(edited ? 'Key 信息与保护额度已更新' : '新 Key 已加入当前服务的凭据池')
  } catch (error) { showError(error) } finally { busy.value = false }
}

async function deleteCredential(credentialId: string) {
  if (!profileForm.id) return
  try {
    await ElMessageBox.confirm(
      '删除后，该 Key 会从服务库中移除，并从当前会话及 Windows 凭据管理器清除；历史用量记录仍会保留。',
      '删除这个 API Key？',
      { confirmButtonText: '确认删除', cancelButtonText: '保留', type: 'warning' },
    )
    await api(`/settings/profiles/${profileForm.id}/credentials/${credentialId}`, { method: 'DELETE' })
    profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${project.value?.id}`)
    settingsPreflight.value = null
    if (credentialForm.id === credentialId) resetCredentialForm()
    ElMessage.success('Key 已删除，历史用量记录仍保留')
  } catch (error) { if (error !== 'cancel') showError(error) }
}

async function checkProfileQuota(target: 'settings' | 'range') {
  const profileId = target === 'range' ? currentProfile.value?.id : profileForm.id
  if (!profileId) return null
  const result = await api<QuotaStatus>(`/generation/preflight/${profileId}`, { method: 'POST' })
  if (target === 'range') rangePreflight.value = result
  else settingsPreflight.value = result
  if (project.value) profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${project.value.id}`)
  return result
}

async function refreshSettingsQuota() {
  try {
    await checkProfileQuota('settings')
    ElMessage.success('基础连通状态已刷新；Key、模型权限与官方余额仍以实际调用和厂商控制台为准')
  } catch (error) { showError(error) }
}

async function savePromptSuffixes() {
  if (!project.value) return
  try {
    await api('/settings/prompts', {
      method: 'PUT', body: JSON.stringify({
        q1_prompt_suffix: project.value.q1_prompt_suffix || '',
        q2_prompt_suffix: project.value.q2_prompt_suffix || '',
      }), headers: { 'Content-Type': 'application/json' },
    })
    ElMessage.success('两组通用提示词已全局保存，所有项目立即共用')
  } catch (error) { showError(error) }
}

function openRange() {
  if (!project.value) return
  if (!currentProfile.value) { section.value = 'settings'; ElMessage.warning('请先配置生图服务'); return }
  range.start_code = questions.value[0]?.code || '001'
  range.end_code = questions.value.at(-1)?.code || '100'
  const defaults = candidateDefaults(rangeModel.value)
  const config = currentProfile.value.config || {}
  range.q1_outputs = candidateValue(config.default_q1_outputs, defaults.image1, rangeLimits.value.image1)
  range.q2_outputs = candidateValue(config.default_q2_outputs, defaults.image2, rangeLimits.value.image2)
  range.singleOnly = Boolean(config.single_output_default ?? true)
  rangeEstimate.value = null
  rangePreflight.value = null
  rangeVisible.value = true
}

function normalizeRange(changed: 'start' | 'end') {
  const start = questions.value.findIndex(item => item.code === range.start_code)
  const end = questions.value.findIndex(item => item.code === range.end_code)
  if (start < 0 || end < 0 || start <= end) return
  if (changed === 'start') range.end_code = range.start_code
  else range.start_code = range.end_code
}

function rangeTooltip(index: number) {
  const question = questions.value[Math.round(index) - 1]
  return question ? `第 ${Math.round(index)} 题 · ${question.code} ${question.title}` : `第 ${Math.round(index)} 题`
}

function selectRangePreset(preset: 'all' | 'current' | 'next10') {
  const last = Math.max(1, questions.value.length)
  if (preset === 'all') {
    rangeSlider.value = [1, last]
    return
  }
  const current = Math.max(1, questions.value.findIndex(item => item.id === currentQuestion.value?.id) + 1)
  rangeSlider.value = preset === 'current' ? [current, current] : [current, Math.min(last, current + 9)]
}

function rangePayload() {
  return {
    project_id: project.value?.id,
    provider_profile_id: currentProfile.value?.id,
    start_code: range.start_code,
    end_code: range.end_code,
    q1_outputs: range.singleOnly ? 1 : range.q1_outputs,
    q2_outputs: range.singleOnly ? 1 : range.q2_outputs,
    parallelism: range.parallelism,
    auto_continue: true,
  }
}

async function calculateEstimate() {
  const profileId = currentProfile.value?.id
  if (!profileId) return
  const requestFingerprint = JSON.stringify(rangePayload())
  rangeCalculating.value = true
  try {
    const [estimate, preflight] = await Promise.all([
      api<Estimate>('/generation/estimate', jsonBody(rangePayload())),
      api<QuotaStatus>(`/generation/preflight/${profileId}`, { method: 'POST' }),
    ])
    if (requestFingerprint !== JSON.stringify(rangePayload())) {
      rangeEstimate.value = null
      rangePreflight.value = null
      ElMessage.info('范围或候选数量已变化，请按当前设置重新计算额度')
      return
    }
    rangeEstimate.value = estimate
    rangePreflight.value = preflight
    if (project.value) profiles.value = await api<ProviderProfile[]>(`/settings/profiles?project_id=${project.value.id}`)
  }
  catch (error) { showError(error) } finally { rangeCalculating.value = false }
}

async function startGeneration() {
  if (!rangeEstimate.value || !rangePreflight.value?.available_credential_count) return
  try {
    await ElMessageBox.confirm(
      `将处理 ${rangeEstimate.value.question_count} 题，最多消耗 ${rangeEstimate.value.total_maximum} 张图片额度，并使用最多 ${range.parallelism} 路并发。`,
      '确认开始生成', { confirmButtonText: '确认并排队', cancelButtonText: '再检查一下', type: 'warning' },
    )
    const started = await api<{ batch_id: string; queued_tasks: number; parallelism: number }>('/generation/start', jsonBody(rangePayload()))
    activeBatchId.value = started.batch_id
    rangeVisible.value = false
    ElMessage.success(`任务已加入队列，当前最多 ${started.parallelism} 路并发。图一确定后才会创建同题图二任务。`)
    await pollQuestions()
  } catch (error) {
    if (error !== 'cancel') showError(error)
  }
}

async function selectAsset(asset: ImageAsset) {
  if (!currentQuestion.value || asset.stale) return
  try {
    await api('/generation/select', jsonBody({
      question_id: currentQuestion.value.id, asset_id: asset.id, stage: asset.stage,
    }))
    ElMessage.success(asset.stage === 'image1' ? '图一已选，正在排队生成同题图二' : '图二已选，本题完成')
    await pollQuestions()
  } catch (error) { showError(error) }
}

function aspectLabel(asset: ImageAsset) {
  const gcd = (left: number, right: number): number => right ? gcd(right, left % right) : left
  const divisor = gcd(asset.width, asset.height) || 1
  return `${asset.width / divisor}:${asset.height / divisor}`
}

async function retryCurrent() {
  const taskId = currentQuestion.value?.latest_failed_task_id
  if (!taskId) return
  try {
    await api(`/generation/tasks/${taskId}/retry`, { method: 'POST' })
    ElMessage.success('失败任务已使用新的请求编号重新排队')
    await pollQuestions()
  } catch (error) { showError(error) }
}

async function retryFailedBatch() {
  if (!batchProgress.value?.failed_question_count || batchActionBusy.value) return
  batchActionBusy.value = true
  try {
    const result = await api<{ retried_count: number }>(
      `/generation/batches/${batchProgress.value.id}/retry-failed`,
      { method: 'POST' },
    )
    ElMessage.success(`已将 ${result.retried_count} 个失败任务重新加入队列`)
    await pollQuestions()
  } catch (error) { showError(error) } finally { batchActionBusy.value = false }
}

async function createExport() {
  if (!project.value) return
  busy.value = true
  try {
    const result = await api<{ directory: string; images_directory: string; question_count: number; image_count: number }>('/exports', jsonBody({ project_id: project.value.id }))
    exported.value = result
    questions.value = await api<Question[]>(`/projects/${project.value.id}/questions`)
    ElMessage.success(`本次增量导出 ${result.question_count} 题，共 ${result.image_count} 张图`)
  } catch (error) { showError(error) } finally { busy.value = false }
}

async function openExportFolder() {
  if (!exported.value) return
  try { await api('/exports/open-folder', jsonBody({ path: exported.value.directory })) }
  catch (error) { showError(error) }
}

async function openDirectory(path?: string) {
  if (!path) return
  try { await api('/system/directory/open', jsonBody({ path })) }
  catch (error) { showError(error) }
}

let polling = 0
let ticking = 0
onMounted(async () => {
  try {
    [models.value] = await Promise.all([
      api<ModelInfo[]>('/settings/models'),
      refreshProjects(),
      refreshSystemInfo(),
    ])
    const params = new URLSearchParams(window.location.search)
    const requestedView = params.get('view') as Section | null
    const requestedProject = params.get('project')
    if (requestedProject && nav.some(item => item.key === requestedView)) {
      await chooseProject(requestedProject, requestedView || 'workbench')
    } else if (requestedView && nav.some(item => item.key === requestedView)) {
      section.value = requestedView
    }
    const requestedSettingsPanel = window.location.hash.slice(1)
    if (section.value === 'settings' && requestedSettingsPanel) {
      await nextTick()
      scrollSettings(requestedSettingsPanel)
    }
  } catch (error) { showError(error) }
  polling = window.setInterval(pollQuestions, 2200)
  ticking = window.setInterval(() => { clock.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  window.clearInterval(polling)
  window.clearInterval(ticking)
})
</script>

<template>
  <div class="app-frame" v-loading="busy">
    <header class="masthead">
      <div class="brand" @click="section = 'projects'">
        <div class="brand-mark"><span>2</span><i>IMG</i></div>
        <div><strong>双图生图工作台</strong><small>QUESTION IMAGE PRODUCTION SYSTEM</small></div>
      </div>
      <div class="project-switch" v-if="project">
        <span>当前项目</span><b>{{ project.name }}</b><em>{{ questions.length }} 题</em>
      </div>
      <button class="theme-toggle" :aria-label="themeActionLabel" :title="themeActionLabel" @click="toggleTheme">
        <span>{{ theme === 'dark' ? '☀' : '◐' }}</span><b>{{ theme === 'dark' ? '日间' : '夜览' }}</b>
      </button>
      <div class="runtime"><span class="live-dot"></span>本地运行</div>
    </header>

    <aside class="rail" aria-label="主导航">
      <button v-for="item in nav" :key="item.key" :class="{ active: section === item.key }" @click="section = item.key">
        <span>{{ item.code }}</span><b>{{ item.label }}</b>
      </button>
    </aside>

    <main class="stage">
      <section v-if="section === 'projects'" class="page projects-page">
        <div class="page-heading">
          <div><span class="kicker">PROJECT INDEX / 00</span><h1>先辨题中意，<br><i>后落画中境。</i></h1></div>
          <button class="signal-button" @click="section = 'import'">＋ 导入新题库</button>
        </div>
        <div class="project-grid" v-if="projects.length">
          <article v-for="(item, index) in projects" :key="item.id" @click="chooseProject(item.id)">
            <span class="serial">P—{{ String(index + 1).padStart(2, '0') }}</span>
            <h2>{{ item.name }}</h2><p>{{ item.question_count }} 道题目</p>
            <div class="project-arrow">进入工作台 <b>↗</b></div>
          </article>
        </div>
        <div class="empty-ledger" v-else>
          <b>EMPTY / 尚无项目</b><p>导入 DOCX、DOC 或 Markdown。导入只做解析预览，不会自动开始生图。</p>
          <el-button type="primary" size="large" @click="section = 'import'">导入第一份题库</el-button>
        </div>
      </section>

      <section v-else-if="section === 'import'" class="page import-page">
        <div class="section-title"><span>01 / IMPORT</span><h1>题库导入与结构预检</h1><p>先识别、再确认。上传文件不会消耗任何生图额度。</p></div>
        <label class="dropzone" :class="{ dragging: importDragging }" @dragover.prevent="importDragging = true" @dragleave.prevent="importDragging = false" @drop.prevent="onDrop">
          <input type="file" accept=".docx,.doc,.md,.markdown" @change="onFile">
          <span class="drop-index">DOC<br>→<br>DATA</span>
          <div><b>将题库拖到这里</b><p>或点击选择文件 · DOCX / DOC / MD · 最大 50MB</p></div>
        </label>
        <div v-if="preview" class="preview-board">
          <div class="metrics">
            <div><span>识别题目</span><b>{{ preview.recognized_count }}</b></div>
            <div><span>结构完整</span><b>{{ preview.complete_count }}</b></div>
            <div class="warn"><span>警告</span><b>{{ preview.warning_count }}</b></div>
            <div class="bad"><span>错误</span><b>{{ preview.error_count }}</b></div>
          </div>
          <div class="preview-table">
            <div v-for="question in preview.questions.slice(0, 12)" :key="question.code">
              <b>{{ question.code }}</b><span>{{ question.title }}</span><em>{{ question.answer }}</em><i v-if="question.priority_blind_test">优先盲测</i>
            </div>
            <p v-if="preview.questions.length > 12">其余 {{ preview.questions.length - 12 }} 题已完成结构检查</p>
          </div>
          <div v-if="preview.issues.length" class="issues">
            <p v-for="issue in preview.issues.slice(0, 6)" :key="`${issue.code}${issue.question_code}`"><b>{{ issue.severity === 'error' ? '错误' : '提示' }}</b>{{ issue.question_code }} {{ issue.message }}</p>
          </div>
          <div class="confirm-strip">
            <el-input v-model="importProjectName" aria-label="项目名称" placeholder="项目名称" />
            <span>确认后仍不会自动生图</span>
            <el-button type="primary" size="large" :disabled="preview.error_count > 0" @click="confirmImport">确认导入 {{ preview.complete_count }} 题</el-button>
          </div>
        </div>
      </section>

      <section v-else-if="section === 'workbench'" class="workbench-page" :class="{ 'has-batch-progress': batchProgress }">
        <template v-if="project">
          <div class="workbench-toolbar">
            <div><span>02 / PRODUCTION DESK</span><b>{{ completedCount }}/{{ questions.length }} 已完成</b></div>
            <el-input v-model="search" placeholder="搜索题号 / 标题 / 答案" clearable />
            <el-button type="primary" @click="openRange">选择范围并生成</el-button>
          </div>
          <div class="output-location-strip">
            <span>GENERATED FILES</span>
            <b>候选图片实时保存到</b>
            <code :title="project.candidate_images_directory">{{ project.candidate_images_directory }}</code>
            <el-button plain @click="openDirectory(project.candidate_images_directory)">打开图片文件夹</el-button>
          </div>
          <div v-if="batchProgress" class="batch-progress-float" :class="batchProgress.status">
            <div class="batch-progress-title">
              <span>CURRENT BATCH · {{ batchProgress.start_code }}–{{ batchProgress.end_code }}</span>
              <b>{{ effectiveBatchStatusText }}</b>
              <small>{{ batchProgress.completed_question_count }}/{{ batchProgress.question_count }} 题完整完成</small>
            </div>
            <div class="batch-progress-bar">
              <div><b>总进度 {{ batchProgress.progress_percent }}%</b><span>{{ batchProgress.completed_stage_count }}/{{ batchProgress.expected_stage_count }} 个图像阶段已生成</span></div>
              <el-progress :percentage="batchProgress.progress_percent" :stroke-width="12" :show-text="false" />
            </div>
            <div class="batch-progress-metrics">
              <span><b>{{ batchProgress.scheduler_active_count }}/{{ batchProgress.scheduler_parallelism }}</b>并发占用</span>
              <span><b>{{ batchProgress.running_task_count }}</b>生成中</span>
              <span><b>{{ batchProgress.queued_task_count }}</b>排队</span>
              <span v-if="batchProgress.retry_waiting_count" class="cooldown"><b>{{ batchProgress.retry_waiting_count }}</b>限流等待</span>
              <span><b>{{ batchProgress.review_question_count }}</b>待选图</span>
              <span v-if="batchProgress.interrupted_task_count" class="bad"><b>{{ batchProgress.interrupted_task_count }}</b>上次中断</span>
              <span v-if="batchProgress.failed_question_count" class="bad"><b>{{ batchProgress.failed_question_count }}</b>失败</span>
            </div>
            <div class="batch-progress-actions">
              <el-button v-if="batchProgress.failed_question_count" size="small" :loading="batchActionBusy" type="danger" @click="retryFailedBatch">一键重试失败项</el-button>
              <el-button v-if="batchProgress.can_pause" size="small" :loading="batchActionBusy" plain @click="pauseBatch">暂停生成</el-button>
              <el-button v-if="batchProgress.can_resume" size="small" :loading="batchActionBusy" type="primary" @click="resumeBatch">继续生成</el-button>
              <small v-if="batchProgress.retry_waiting_count">无需手动重试</small>
            </div>
          </div>
          <div class="workbench-grid">
            <aside class="question-list">
              <button v-for="q in visibleQuestions" :key="q.id" :class="{ active: currentQuestion?.id === q.id }" @click="currentQuestionId = q.id">
                <b>{{ q.code }}</b><span>{{ q.title }}</span><i :class="statusTone(q.state)">{{ statusLabel(q.state) }}</i>
              </button>
            </aside>
            <section class="canvas" v-if="currentQuestion">
              <header><span>Q.{{ currentQuestion.code }}</span><h2>{{ currentQuestion.title }}</h2><em>答案 · {{ currentQuestion.answer }}</em></header>
              <div class="image-columns">
                <div class="image-stage">
                  <div class="stage-label"><b>IMAGE / 01</b><span>{{ currentQuestion.selected_image1_id ? '已确定' : '先生成并选择' }}</span></div>
                  <div class="candidate-grid" v-if="q1Assets.length">
                    <article v-for="asset in q1Assets" :key="asset.id" :class="{ selected: asset.selected }">
                      <img :src="asset.url" :alt="`题目 ${currentQuestion.code} 第一张候选图 ${asset.output_index}`">
                      <span>#{{ String(asset.output_index).padStart(2, '0') }}</span>
                      <em>{{ asset.width }}×{{ asset.height }} · {{ aspectLabel(asset) }}</em>
                      <b v-if="asset.selected">已选择</b>
                      <button v-else @click="selectAsset(asset)">选择此图</button>
                    </article>
                  </div>
                  <div v-else class="image-empty"><span>01</span><p>等待第一张图<br>它不依赖任何参考图</p></div>
                </div>
                <div class="dependency-arrow"><b>→</b><span>同题引用</span></div>
                <div class="image-stage" :class="{ locked: !currentQuestion.selected_image1_id }">
                  <div class="stage-label"><b>IMAGE / 02</b><span>{{ currentQuestion.selected_image1_id ? '引用当前图一' : '等待图一' }}</span></div>
                  <div v-if="selectedImage1" class="reference-chip"><img :src="selectedImage1.url"><span>固定参考 · {{ currentQuestion.code }}</span></div>
                  <div class="candidate-grid" v-if="q2Assets.length">
                    <article v-for="asset in q2Assets" :key="asset.id" :class="{ selected: asset.selected, stale: asset.stale }">
                      <img :src="asset.url" :alt="`题目 ${currentQuestion.code} 第二张候选图 ${asset.output_index}`">
                      <span>#{{ String(asset.output_index).padStart(2, '0') }}</span>
                      <em>{{ asset.width }}×{{ asset.height }} · {{ aspectLabel(asset) }}</em>
                      <b v-if="asset.stale">引用已失效</b><b v-else-if="asset.selected">已选择</b>
                      <button v-else-if="!asset.stale" @click="selectAsset(asset)">选择此图</button>
                    </article>
                  </div>
                  <div v-else class="image-empty"><span>02</span><p>{{ currentQuestion.selected_image1_id ? '图一就绪后自动排队' : '必须先选定同题第一张图' }}</p></div>
                </div>
              </div>
            </section>
            <aside class="prompt-panel" v-if="currentQuestion">
              <div class="panel-heading"><span>PROMPT SNAPSHOT</span><b>{{ currentProfile?.display_name || '未配置模型' }}</b></div>
              <div class="prompt-block"><label>图一 · 文档原始提示词</label><p>{{ currentQuestion.image1_prompt }}</p></div>
              <div class="prompt-block suffix"><label>图一 · 通用提示词</label><p>{{ project.q1_prompt_suffix || '（空，不添加）' }}</p></div>
              <details><summary>查看图一最终提示词</summary><pre>{{ finalPrompt1 }}</pre></details>
              <div class="rule"></div>
              <div class="prompt-block"><label>图二 · 文档原始提示词</label><p>{{ currentQuestion.image2_prompt }}</p></div>
              <div class="prompt-block suffix"><label>图二 · 通用提示词</label><p>{{ project.q2_prompt_suffix || '（空，不添加）' }}</p></div>
              <details><summary>查看图二最终提示词</summary><pre>{{ finalPrompt2 }}</pre></details>
              <div v-if="currentQuestion.latest_failed_task_id" class="retry-card">
                <b>本题最近一次生成失败</b>
                <p class="failure-message">{{ currentQuestion.latest_error || '任务被中断或服务未返回有效图片' }}</p>
                <div class="failure-advice"><span>建议排查</span><p>{{ failureAdvice }}</p></div>
                <div class="failure-actions">
                  <el-button type="primary" @click="inspectCurrentModel">检查模型设置</el-button>
                  <el-button plain @click="retryCurrent">仍要重试</el-button>
                  <a v-if="rangeModel?.provider_console_url" :href="rangeModel.provider_console_url" target="_blank" rel="noopener noreferrer">打开厂商控制台 ↗</a>
                </div>
              </div>
              <el-button @click="section = 'settings'">编辑通用提示词与模型</el-button>
            </aside>
          </div>
        </template>
        <div v-else class="empty-ledger"><b>NO PROJECT / 未选择项目</b><p>请先从项目页选择项目或导入题库。</p><el-button type="primary" @click="section = 'projects'">返回项目</el-button></div>
      </section>

      <section v-else-if="section === 'settings'" class="page settings-page">
        <div class="section-title"><span>03 / GLOBAL SETTINGS</span><h1>全局生图设置</h1><p>模型、画幅、候选数量、全部 Key 与通用提示词独立于题库保存，所有项目直接共用。</p></div>
        <template v-if="project">
          <nav class="settings-jump" aria-label="设置页快捷导航">
            <button @click="scrollSettings('model-settings')"><span>01</span>模型与比例</button>
            <button @click="scrollSettings('candidate-settings')"><span>02</span>候选图默认值</button>
            <button @click="scrollSettings('key-settings')"><span>03</span>API Key 与额度</button>
            <button @click="scrollSettings('prompt-settings')"><span>04</span>通用提示词</button>
          </nav>
          <div class="settings-grid">
            <article id="model-settings" class="settings-card provider-settings full-card">
              <header><span>A</span><div><h2>模型、提供商与画面比例</h2><p>尺寸可单独设定；预设已按厂商接口格式区分，仍可手动输入合法尺寸。</p></div></header>
              <div class="service-mode" role="group" aria-label="服务类型">
                <button :class="{ active: profileForm.provider !== 'custom' }" @click="newPresetProfile"><b>预设模型</b><span>Seedream / Qwen / Wan</span></button>
                <button :class="{ active: profileForm.provider === 'custom' }" @click="newCustomProfile"><b>自定义服务</b><span>OpenAI 兼容接口</span></button>
              </div>
              <div v-if="profiles.length" class="saved-services">
                <span>全局服务库 · 所有项目共用</span>
                <button v-for="p in profiles" :key="p.id" @click="chooseSavedProfile(p)" :class="{ active: p.id === profileForm.id }">{{ p.display_name }} <i>{{ p.secret_configured ? `Key ····${p.last_four}` : '未配置 Key' }}</i></button>
              </div>
              <label>已验证模型</label>
              <el-select v-if="profileForm.provider !== 'custom'" v-model="profileForm.model_id" style="width: 100%" @change="chooseModel">
                <el-option v-for="model in models" :key="`${model.provider}${model.model}`" :label="`${model.display_name} · ${model.default_size} · ${model.support_level === 'optimized' ? '已特化' : '测试适配'}`" :value="model.model" />
              </el-select>
              <div v-if="formModel" class="support-level-note" :class="formModel.support_level">
                <b>{{ formModel.support_level === 'optimized' ? '当前重点特化' : '当前为测试适配' }}</b>
                <span>{{ formModel.support_level === 'optimized' ? 'Seedream 5.0 Lite 已完成尺寸、组图、图生图、错误处理与双接口适配。' : '已实现基础调用，但不同账号、地域和厂商版本仍可能存在差异，请先小范围试跑。' }}</span>
              </div>
              <template v-else>
                <label>服务名称</label><el-input v-model="profileForm.display_name" />
                <label>自定义模型 ID</label><el-input v-model="profileForm.model_id" placeholder="vendor-model-id" />
                <div class="inline-fields"><div><label>最多候选</label><el-input-number v-model="profileForm.max_outputs" :min="1" :max="15" /></div><div><label>默认尺寸</label><el-input v-model="profileForm.default_size" /></div></div>
              </template>
              <div v-if="formModel" class="official-links">
                <a v-if="activeApiKeyUrl" :href="activeApiKeyUrl" target="_blank" rel="noopener noreferrer"><b>获取 API Key</b><span>{{ isSeedream && profileForm.api_mode === 'agent_plan' ? '创建 Agent Plan 专属 Key' : '打开厂商官方页面' }} ↗</span></a>
                <a v-if="activeDocumentationUrl" :href="activeDocumentationUrl" target="_blank" rel="noopener noreferrer"><b>模型 API 文档</b><span>{{ formModel.display_name }} ↗</span></a>
                <a v-if="formModel.provider_console_url" :href="formModel.provider_console_url" target="_blank" rel="noopener noreferrer"><b>厂商控制台</b><span>额度与账单 ↗</span></a>
              </div>
              <div v-if="isSeedream" class="api-mode-panel">
                <div class="advanced-title"><span>BILLING CHANNEL</span><b>火山方舟调用通道</b></div>
                <div class="api-mode-options" role="radiogroup" aria-label="火山方舟调用通道">
                  <button type="button" :class="{ active: profileForm.api_mode === 'standard' }" @click="profileForm.api_mode = 'standard'">
                    <b>普通按量 API</b><span>按火山方舟标准图片调用计费</span>
                  </button>
                  <button type="button" :class="{ active: profileForm.api_mode === 'agent_plan' }" @click="profileForm.api_mode = 'agent_plan'">
                    <b>Agent Plan 套餐 API</b><span>消耗已订阅套餐的 AFP 额度</span>
                  </button>
                </div>
                <div class="api-endpoint-preview" :class="profileForm.api_mode">
                  <span>{{ profileForm.api_mode === 'agent_plan' ? '套餐接口' : '按量接口' }}</span><code>{{ effectiveVolcengineEndpoint }}</code>
                </div>
                <p v-if="profileForm.api_mode === 'agent_plan'" class="api-mode-warning"><b>请使用 Agent Plan 控制台创建的专属 API Key。</b> 官方明确提示：套餐用户若调用普通 <code>/api/v3</code> 图片接口，会产生套餐外按量费用。</p>
                <p v-else class="api-mode-standard-note">未订阅 Agent Plan，或希望使用普通模型按量计费时选择此项。</p>
              </div>
              <label>{{ isSeedream ? 'API 主机（通常无需修改）' : 'API 地址' }}</label><el-input v-model="profileForm.base_url" placeholder="https://..." />
              <label v-if="profileForm.provider === 'alibaba'">Workspace ID（可选）</label><el-input v-if="profileForm.provider === 'alibaba'" v-model="profileForm.workspace_id" />
              <div class="advanced-controls" v-if="profileForm.provider !== 'custom'">
                <div class="advanced-title"><span>ASPECT & MODEL CONTROLS</span><b>比例与当前模型专属参数</b></div>
                <label class="control-label">常用画面比例</label>
                <div class="ratio-presets">
                  <button v-for="preset in formSizePresets" :key="preset.ratio" :class="{ active: profileForm.size === preset.value }" @click="profileForm.size = preset.value"><b>{{ preset.ratio }}</b><span>{{ preset.label }}</span><i>{{ preset.value }}</i><small v-if="preset.recommendation">{{ preset.recommendation }}</small></button>
                </div>
                <div class="inline-fields">
                  <div><label>实际发送尺寸（可自定义）</label><el-input v-model="profileForm.size" :placeholder="isSeedream ? '2K / 2304x1728' : '2048*2048'" /></div>
                  <div v-if="isSeedream || isQwen"><label>随机种子（可空）</label><el-input-number v-model="profileForm.seed" :min="0" :max="2147483647" controls-position="right" /></div>
                </div>
                <div v-if="profileForm.model_id === 'doubao-seedream-5-0-lite-260128'" class="provider-default-note size-rule-note">
                  <b>Seedream 5.0 Lite 尺寸下限</b>
                  <span>显式宽高至少需要 3,686,400 总像素。旧版的 2048x1536 等小尺寸会自动升级为相同比例的合法尺寸。</span>
                </div>
                <div v-if="isSeedream" class="guidance-control">
                  <div class="guidance-heading"><div><label>提示词遵循强度（guidance_scale）</label><span>官方没有“普遍最佳值”</span></div><el-switch v-model="customGuidance" inline-prompt active-text="自定义" inactive-text="模型默认" /></div>
                  <template v-if="customGuidance">
                    <el-slider v-model="profileForm.guidance_scale" :min="1" :max="10" :step="0.1" :marks="guidanceMarks" show-input />
                    <div class="guidance-note"><b>数值低</b><span>构图更自由，但可能漏掉细节</span><b>数值高</b><span>更严格贴合提示词，但画面可能更僵硬</span><button type="button" @click="profileForm.guidance_scale = 5.5">恢复 5.5</button></div>
                    <p>5.5 只是软件提供的平衡起点。若经常漏掉角色数量、位置或关键道具，可逐步调到 6–7，不建议直接拉满。</p>
                  </template>
                  <div v-else class="provider-default-note"><b>当前跟随模型默认</b><span>软件不会发送 guidance_scale，由厂商按当前模型版本处理。</span></div>
                </div>
                <el-checkbox v-model="profileForm.watermark">添加厂商水印</el-checkbox>
                <el-checkbox v-if="isQwen" v-model="profileForm.prompt_extend">Qwen 智能扩写提示词（关闭时更严格遵循 DOC 原文）</el-checkbox>
                <el-checkbox v-if="isWan" v-model="profileForm.thinking_mode">Wan 图一思考模式（仅无参考图时生效）</el-checkbox>
                <p>同一服务配置的图一、图二使用这里的尺寸；模型并未把比例写死，但每家尺寸格式与上限不同。界面只发送当前模型支持的字段。</p>
              </div>
              <label>首个 API Key（可选） <em v-if="profileForm.id">留空则保持现有 Key</em></label>
              <el-input v-model="profileForm.api_key" type="password" show-password autocomplete="new-password" placeholder="不会回显已保存密钥" />
              <el-checkbox v-model="profileForm.remember_secret">使用 Windows 凭据管理器记住密钥</el-checkbox>
              <el-button type="primary" @click="saveProfile">保存并设为当前服务</el-button>
            </article>

            <article id="candidate-settings" class="settings-card candidate-settings full-card">
              <header><span>B</span><div><h2>候选图默认值</h2><p>这里保存默认值；每次开始一批任务时仍可临时修改。</p></div></header>
              <div class="single-output-switch">
                <el-switch v-model="profileForm.single_output_default" size="large" />
                <div><b>默认只生成一张候选图</b><p>开启后图一、图二各请求 1 张，返回后自动选择；不需要人工确认。</p></div>
              </div>
              <div class="candidate-defaults" :class="{ disabled: profileForm.single_output_default }">
                <div><label>图一候选数 <em>模型最多 {{ formLimits.image1 }}</em></label><el-input-number v-model="profileForm.default_q1_outputs" :min="1" :max="formLimits.image1" :disabled="profileForm.single_output_default" /></div>
                <div><label>图二候选数 <em>模型最多 {{ formLimits.image2 }}</em></label><el-input-number v-model="profileForm.default_q2_outputs" :min="1" :max="formLimits.image2" :disabled="profileForm.single_output_default" /></div>
                <p>若厂商实际只返回 1 张，该阶段仍会自动选择；图二始终等同题图一确认后才会生成。</p>
              </div>
              <el-button type="primary" @click="saveProfile">保存候选默认值与当前模型设置</el-button>
            </article>

            <article id="key-settings" class="settings-card key-settings full-card">
              <header><span>C</span><div><h2>API Key、备用池与额度面板</h2><p>可自由添加任意数量 Key；同一模型内按优先级切换，不会跨服务混用。</p></div></header>
              <div v-if="!editingProfile" class="key-empty"><b>先保存上方模型配置</b><p>保存后即可在这里连续添加主 Key、备用 Key，并分别设置保护额度。</p><el-button @click="scrollSettings('model-settings')">返回模型设置</el-button></div>
              <template v-else>
                <div class="quota-status-strip">
                  <b>{{ settingsPreflight?.profile_id === editingProfile.id ? settingsPreflight.available_credential_count : credentialRows.filter(item => item.enabled && item.secret_configured && item.status === 'active').length }}</b><span>{{ settingsPreflight?.profile_id === editingProfile.id ? '个 Key 通过基础检查' : '个启用 Key' }}</span>
                  <p>{{ settingsPreflight?.profile_id === editingProfile.id ? settingsPreflight.official_quota.note : '下方进度是用户填写的本机保护额度，不是厂商官方账单；精确余额请到控制台查看。' }}</p>
                  <a v-if="formModel?.provider_console_url" :href="formModel.provider_console_url" target="_blank" rel="noopener noreferrer">打开官方额度控制台 ↗</a>
                  <el-button size="small" @click="refreshSettingsQuota">运行基础连通检查</el-button>
                </div>
                <div class="quota-cards">
                  <article v-for="credential in credentialRows" :key="credential.id" :class="credential.status">
                    <div class="quota-card-head"><div><b>{{ credential.label }}</b><span>{{ credential.account_label || '未填写账户备注' }} · 优先级 #{{ credential.priority }}</span></div><em>····{{ credential.last_four || '----' }}</em><small>{{ credentialStatus(credential.status) }}</small></div>
                    <div class="quota-progress" :class="{ unknown: credentialProgress(credential) == null }">
                      <el-progress :percentage="credentialProgress(credential) ?? 0" :stroke-width="10" :show-text="false" />
                      <div v-if="credentialProgress(credential) != null"><b>本机保护剩余 {{ credential.manual_remaining_images }} 张</b><span>本机累计生成 {{ credential.local_generated_images || 0 }} 张 · 参考费用 ¥{{ credential.local_estimated_cost_cny || '0.00' }}</span></div>
                      <div v-else><b>未设置本机保护额度</b><span>点击编辑填写后，生成时会逐张扣减并显示进度</span></div>
                    </div>
                    <p v-if="credential.preflight_message">{{ credential.preflight_message }}</p>
                    <div class="quota-actions"><button @click="editCredential(credential)">编辑 / 补充额度</button><button class="danger" @click="deleteCredential(credential.id)">删除 Key</button></div>
                  </article>
                  <div v-if="!credentialRows.length" class="key-empty compact"><b>还没有 Key</b><p>在下方添加第一把；之后可继续添加，不限一把。</p></div>
                </div>
                <div id="credential-editor" class="credential-add">
                  <div class="credential-editor-title"><b>{{ credentialForm.id ? '编辑现有 Key' : '添加一把新 Key' }}</b><button v-if="credentialForm.id" @click="resetCredentialForm">取消编辑</button></div>
                  <div><label>密钥名称</label><el-input v-model="credentialForm.label" placeholder="如：主 Key / 备用 Key 2" /></div>
                  <div><label>账户备注</label><el-input v-model="credentialForm.account_label" placeholder="如：账号 B" /></div>
                  <div><label>优先级（数字越小越先用）</label><el-input-number v-model="credentialForm.priority" :min="1" :max="10000" /></div>
                  <div><label>当前本机保护剩余额度</label><el-input-number v-model="credentialForm.manual_remaining_images" :min="0" placeholder="可空" /></div>
                  <div class="key-field"><label>{{ credentialForm.id ? '替换 API Key（留空则不更换）' : 'API Key' }}</label><el-input v-model="credentialForm.api_key" type="password" show-password autocomplete="new-password" placeholder="密钥只写入 Windows 凭据管理器或本次运行内存" /></div>
                  <el-checkbox v-model="credentialForm.remember_secret">记入 Windows 凭据管理器</el-checkbox>
                  <el-button type="primary" :disabled="!credentialForm.id && !credentialForm.api_key" @click="addCredential">{{ credentialForm.id ? '保存 Key 修改' : '＋ 添加到当前服务' }}</el-button>
                </div>
              </template>
            </article>

            <article id="prompt-settings" class="settings-card prompt-settings full-card">
              <header><span>D</span><div><h2>分图通用提示词</h2><p>分别追加到 DOC 文档每道题提示词尾部；默认为空。</p></div></header>
              <div class="prompt-fields">
                <div><label>第一张图通用提示词 <em>IMAGE 01</em></label><el-input v-model="project.q1_prompt_suffix" type="textarea" :rows="5" placeholder="为空时不修改文档提示词" /></div>
                <div><label>第二张图通用提示词 <em>IMAGE 02</em></label><el-input v-model="project.q2_prompt_suffix" type="textarea" :rows="5" placeholder="可与第一张图完全不同" /></div>
              </div>
              <p class="global-settings-note"><b>全局共用</b> 保存后会用于所有现有项目和以后导入的新题库；需要不同画风时可随时在这里修改。</p>
              <el-button type="primary" @click="savePromptSuffixes">全局保存通用提示词</el-button>
            </article>
          </div>
        </template>
        <div v-else class="empty-ledger"><b>先选择项目</b><p>生图配置会绑定到当前项目。</p></div>
      </section>

      <section v-else-if="section === 'exports'" class="page exports-page">
        <div class="section-title"><span>04 / FINAL ASSETS</span><h1>成对成品与增量导出</h1><p>每次只导出上次成功导出后新增或变更的完整题目；图片和清单直接平铺在短批次目录中。</p></div>
        <template v-if="project">
          <div class="export-summary"><div><span>本次待导出题目</span><b>{{ exportPendingCount }}</b><em>/ {{ completedCount }} 已完成</em></div><p>批次目录：<code>exports\20260722-01</code><br>图片命名：<code>001__答案__01.png</code> 与 <code>001__答案__02.png</code></p><el-button type="primary" size="large" :loading="busy" :disabled="!exportPendingCount" @click="createExport">导出新增 / 变更配对</el-button></div>
          <div class="final-pairs">
            <article v-for="q in questions.filter(item => item.state === 'completed')" :key="q.id">
              <header><b>{{ q.code }}</b><span>{{ q.answer }}</span></header>
              <div><img v-if="q.assets.find(a => a.id === q.selected_image1_id)" :src="q.assets.find(a => a.id === q.selected_image1_id)?.url"><i>01</i></div>
              <div><img v-if="q.assets.find(a => a.id === q.selected_image2_id)" :src="q.assets.find(a => a.id === q.selected_image2_id)?.url"><i>02</i></div>
            </article>
          </div>
          <div class="export-result" v-if="exported"><b>EXPORT READY</b><p>{{ exported.directory }}</p><span>{{ exported.question_count }} 题 · {{ exported.image_count }} 张图</span><el-button @click="openExportFolder">打开导出文件夹</el-button></div>
        </template>
      </section>

      <section v-else class="page about-page">
        <div class="section-title"><span>05 / ABOUT</span><h1>关于 PairForge</h1><p>题意先立，双图后成；让一整套题库的画面生产保持有序、可续、可追溯。</p></div>
        <div class="about-grid">
          <article class="about-intro">
            <span>PAIRFORGE / {{ systemInfo?.version || '0.5.1' }}</span>
            <h2>{{ systemInfo?.description || 'PairForge：面向《这是谐音梗》创意工坊题库制作的批量 AI 配图工具，支持自定义生图 API，简化成对图片的生成与管理流程。' }}</h2>
            <p>PairForge 服务于《这是谐音梗》创意工坊从题库文档到成对配图成品的制作环节。它坚持同题图一先生成并确定，随后才让图二引用该图继续创作；题目之间、模型之间和 API Key 之间都保持清晰边界。</p>
            <div class="about-version"><b>VERSION</b><strong>{{ systemInfo?.version || '0.5.1' }}</strong><em>Windows · Local First</em></div>
          </article>
          <a class="repository-card" :href="systemInfo?.repository_url || 'https://github.com/kaguraaya/PairForge'" target="_blank" rel="noopener noreferrer">
            <span>OPEN SOURCE REPOSITORY</span><b>kaguraaya / PairForge</b><p>查看源码、模板、构建说明与后续版本</p><i>↗</i>
          </a>
          <article class="storage-card">
            <header><span>PORTABLE STORAGE</span><h2>数据与程序放在一起</h2></header>
            <div><b>数据目录</b><code>{{ systemInfo?.data_directory || '正在读取…' }}</code></div>
            <div><b>项目图片</b><code>{{ systemInfo?.projects_directory || '正在读取…' }}</code></div>
            <div><b>缓存目录</b><code>{{ systemInfo?.cache_directory || '正在读取…' }}</code></div>
            <p>生成中的候选图位于每个项目的 <code>assets\q1_candidates</code> 与 <code>assets\q2_candidates</code>；点击“成品导出”后，可直接上传的增量图片位于该项目 <code>exports\日期-批次</code>，图片与清单同级平铺。工作台顶部会显示当前项目的精确路径。</p>
            <div class="storage-actions"><el-button type="primary" plain @click="openDirectory(systemInfo?.data_directory)">打开数据目录</el-button><el-button plain @click="openDirectory(systemInfo?.projects_directory)">打开项目图片目录</el-button></div>
            <p>数据库、候选图与成品不会被“清除缓存”删除。若移动软件，请将 EXE 与同级 <code>PairForge_Data</code> 文件夹一起移动。</p>
          </article>
          <article class="cache-card">
            <span>TEMPORARY CACHE</span><div><b>{{ systemInfo?.cache_file_count || 0 }}</b><em>个临时文件</em><strong>{{ formatBytes(systemInfo?.cache_bytes || 0) }}</strong></div>
            <p>这里只统计导入预览、旧 DOC 转换件等可重新生成的临时文件。</p>
            <el-button type="danger" plain :loading="cacheBusy" @click="clearCache">清除临时缓存</el-button>
          </article>
        </div>
      </section>
    </main>

    <el-dialog v-model="rangeVisible" title="选择生成范围、候选数量与并发" width="720px" top="3vh" destroy-on-close>
      <div class="range-form">
        <div class="range-summary">
          <span>已选择</span><b>{{ rangeQuestionCount }}</b><em>题</em>
          <p>{{ rangeStartQuestion?.code }} {{ rangeStartQuestion?.title }} <i>→</i> {{ rangeEndQuestion?.code }} {{ rangeEndQuestion?.title }}</p>
        </div>
        <div class="range-slider-shell">
          <div class="range-slider-heading"><b>拖动两端选择题目范围</b><span>按题库顺序，不会跨题混用图片</span></div>
          <el-slider v-model="rangeSlider" range :min="1" :max="Math.max(1, questions.length)" :step="1" :marks="rangeMarks" :format-tooltip="rangeTooltip" />
        </div>
        <div class="range-presets"><button type="button" @click="selectRangePreset('all')">全部题目</button><button type="button" @click="selectRangePreset('current')">仅当前题</button><button type="button" @click="selectRangePreset('next10')">从当前题起 10 题</button></div>
        <div class="range-codes">
          <div><label>起始题目（也可精确选择）</label><el-select v-model="range.start_code" filterable @change="normalizeRange('start')"><el-option v-for="item in questions" :key="`start-${item.id}`" :label="`${item.code} · ${item.title}`" :value="item.code" /></el-select></div>
          <b>→</b>
          <div><label>结束题目</label><el-select v-model="range.end_code" filterable @change="normalizeRange('end')"><el-option v-for="item in questions" :key="`end-${item.id}`" :label="`${item.code} · ${item.title}`" :value="item.code" /></el-select></div>
        </div>
        <el-checkbox v-model="range.singleOnly" size="large"><b>只生成一张候选图</b>（实际只有一张时自动选择，无需人工确认）</el-checkbox>
        <div class="candidate-counts" :class="{ disabled: range.singleOnly }">
          <div><label>图一候选上限（模型最多 {{ rangeLimits.image1 }}）</label><el-input-number v-model="range.q1_outputs" :min="1" :max="rangeLimits.image1" :disabled="range.singleOnly" /></div>
          <div><label>图二候选上限（模型最多 {{ rangeLimits.image2 }}）</label><el-input-number v-model="range.q2_outputs" :min="1" :max="rangeLimits.image2" :disabled="range.singleOnly" /></div>
        </div>
        <div class="parallelism-control">
          <div><b>批量并发任务数</b><span>当前最多同时调用 {{ range.parallelism }} 个生图任务</span></div>
          <el-slider v-model="range.parallelism" :min="1" :max="12" :step="1" :marks="parallelismMarks" show-stops />
          <p>推荐 8 路；单 Key 若出现 429/限流可降到 4，多 Key 或更高并发额度可尝试 10–12。</p>
        </div>
        <el-button v-if="!rangeEstimate" type="primary" size="large" :loading="rangeCalculating" @click="calculateEstimate">计算额度并继续</el-button>
        <div v-else class="quota-ticket">
          <span>ESTIMATED QUOTA</span><div><b>{{ rangeEstimate.question_count }}</b><i>题</i><b>{{ rangeEstimate.image1_maximum }}</b><i>图一上限</i><b>{{ rangeEstimate.image2_maximum }}</b><i>图二上限</i></div>
          <p>最多消耗 <strong>{{ rangeEstimate.total_maximum }}</strong> 张图片额度 · 最多 {{ range.parallelism }} 路并发 · 参考费用 ¥{{ rangeEstimate.estimated_cost_cny }} · 价格日期 {{ rangeEstimate.price_checked_on }}</p>
          <small v-if="rangeEstimate.actual_may_be_lower">该模型为“最多返回”语义，实际图片数可能低于上限；实际只返回一张仍会自动选择。</small>
          <div v-if="rangePreflight" class="range-preflight" :class="{ blocked: !rangePreflight.available_credential_count }">
            <b>{{ rangePreflight.available_credential_count ? `${rangePreflight.available_credential_count} 个 Key 通过基础检查` : '没有可调用的 Key' }}</b>
            <p>{{ rangePreflight.official_quota.note }}</p>
            <a v-if="rangePreflight.official_quota.console_url" :href="rangePreflight.official_quota.console_url" target="_blank" rel="noopener noreferrer">到官方控制台核对余额 ↗</a>
          </div>
          <el-button type="primary" size="large" :disabled="!rangePreflight?.available_credential_count" @click="startGeneration">确认开始生成</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.app-frame { min-height: 100vh; display: grid; grid-template: 76px 1fr / 88px 1fr; }
.masthead { grid-column: 1 / -1; display: flex; align-items: center; padding: 0 24px 0 16px; border-bottom: 1px solid var(--ink); background: var(--masthead); backdrop-filter: blur(12px); position: sticky; top: 0; z-index: 20; }
.brand { display: flex; align-items: center; gap: 12px; min-width: 330px; cursor: pointer; }
.brand-mark { width: 50px; height: 50px; color: var(--on-solid); background: var(--solid); display: grid; grid-template: 1fr / 1fr 1fr; align-items: center; padding: 6px; transform: rotate(-2deg); }
.brand-mark span { font: 900 30px/1 Rockwell, serif; }.brand-mark i { writing-mode: vertical-rl; font-style: normal; font-size: 8px; letter-spacing: .18em; }
.brand strong { display: block; font: 800 20px/1.15 Rockwell, "FZYaoti", serif; }.brand small { font-size: 8px; letter-spacing: .18em; color: var(--muted); }
.project-switch { margin-left: 24px; padding-left: 24px; border-left: 1px solid var(--line); display: flex; align-items: baseline; gap: 10px; }.project-switch span,.runtime { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }.project-switch em { font-style: normal; padding: 3px 6px; background: var(--paper-deep); font-size: 10px; }
.theme-toggle { margin-left: auto; min-width: 74px; height: 36px; display: flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid var(--line); color: var(--ink); background: var(--panel); cursor: pointer; }.theme-toggle:hover { border-color: var(--signal); color: var(--signal); }.theme-toggle span { font-size: 16px; }.theme-toggle b { font-size: 10px; }.runtime { margin-left: 16px; display: flex; gap: 8px; align-items: center; }.live-dot { width: 8px; height: 8px; border-radius: 50%; background: #22a06b; box-shadow: 0 0 0 4px rgba(34,160,107,.12); }
.rail { grid-row: 2; border-right: 1px solid var(--ink); background: var(--paper-deep); position: sticky; top: 76px; height: calc(100vh - 76px); z-index: 10; }
.rail button { width: 100%; min-height: 84px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 5px; position: relative; }.rail button span { font: 700 9px/1 monospace; color: var(--muted); }.rail button b { font-size: 13px; }.rail button:hover,.rail button.active { background: var(--solid); color: var(--on-solid); }.rail button.active::after { content: ''; position: absolute; right: -7px; width: 13px; height: 13px; background: var(--signal); transform: rotate(45deg); }.rail button.active span { color: var(--muted); }
.stage { min-width: 0; }.page { min-height: calc(100vh - 76px); padding: clamp(28px, 4vw, 64px); max-width: 1540px; margin: auto; animation: reveal .35s ease both; }@keyframes reveal { from { opacity: 0; transform: translateY(8px); } }
.page-heading { display: flex; justify-content: space-between; align-items: end; border-bottom: 1px solid var(--ink); padding-bottom: 28px; }.kicker,.section-title>span,.workbench-toolbar span { font: 700 10px/1 monospace; letter-spacing: .16em; color: var(--signal); }.page-heading h1 { margin: 12px 0 0; font: 800 clamp(38px,5vw,76px)/.98 Rockwell,"FZYaoti",serif; letter-spacing: -.04em; }.page-heading h1 i { color: var(--signal); font-style: normal; }.signal-button { border: 0; background: var(--signal); color: white; padding: 18px 24px; font-weight: 800; box-shadow: 8px 8px 0 var(--ink); }.signal-button:hover { transform: translate(3px,3px); box-shadow: 5px 5px 0 var(--ink); }
.project-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 1px; background: var(--line); border: 1px solid var(--ink); margin-top: 34px; }.project-grid article { background: var(--panel); padding: 26px; min-height: 260px; display: flex; flex-direction: column; cursor: pointer; }.project-grid article:hover { background: var(--surface-hover); }.serial { font: 700 10px monospace; color: var(--signal); }.project-grid h2 { margin: 35px 0 8px; font: 800 25px Rockwell,"FZYaoti",serif; }.project-grid p { color: var(--muted); }.project-arrow { margin-top: auto; border-top: 1px solid var(--line); padding-top: 15px; display: flex; justify-content: space-between; }.project-arrow b { font-size: 20px; }
.empty-ledger { max-width: 760px; margin: 80px auto; padding: 50px; border: 1px solid var(--ink); background: var(--panel); box-shadow: 12px 12px 0 var(--paper-deep); }.empty-ledger>b { font: 800 26px Rockwell,serif; }.empty-ledger p { color: var(--muted); line-height: 1.8; }
.section-title { display: grid; grid-template-columns: 170px 1fr; border-bottom: 1px solid var(--ink); padding-bottom: 24px; margin-bottom: 28px; }.section-title h1 { margin: 0; font: 800 clamp(34px,4vw,58px)/1 Rockwell,"FZYaoti",serif; }.section-title p { grid-column: 2; margin: 10px 0 0; color: var(--muted); }
.dropzone { height: 230px; border: 1px dashed var(--ink); display: flex; align-items: center; justify-content: center; gap: 36px; background: var(--surface-glass); cursor: pointer; transition: .2s; }.dropzone.dragging,.dropzone:hover { background: var(--surface-hover); border-color: var(--signal); }.dropzone input { display: none; }.drop-index { font: 900 22px/1 Rockwell,serif; color: var(--signal); text-align: center; }.dropzone b { font: 800 28px Rockwell,"FZYaoti",serif; }.dropzone p { color: var(--muted); }
.preview-board { margin-top: 24px; border: 1px solid var(--ink); background: var(--panel); }.metrics { display: grid; grid-template-columns: repeat(4,1fr); border-bottom: 1px solid var(--ink); }.metrics div { padding: 18px; border-right: 1px solid var(--line); }.metrics span { display: block; font-size: 11px; color: var(--muted); }.metrics b { font: 800 36px Rockwell,serif; }.metrics .warn b { color: var(--warn); }.metrics .bad b { color: var(--bad); }.preview-table>div { display: grid; grid-template-columns: 70px 1fr 180px 100px; padding: 11px 16px; border-bottom: 1px solid var(--line); font-size: 13px; }.preview-table em { font-style: normal; }.preview-table i { font-style: normal; color: var(--signal); font-size: 11px; }.preview-table>p { padding: 10px 16px; color: var(--muted); }.issues { padding: 10px 16px; background: var(--surface-warn); }.issues p { margin: 6px 0; font-size: 12px; }.issues b { margin-right: 12px; color: var(--bad); }.confirm-strip { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 18px; padding: 18px; border-top: 1px solid var(--ink); }.confirm-strip span { color: var(--muted); font-size: 12px; }
.workbench-page { height: calc(100vh - 76px); overflow: hidden; }.workbench-toolbar { height: 60px; padding: 11px 16px; border-bottom: 1px solid var(--ink); display: flex; align-items: center; gap: 16px; }.workbench-toolbar>div:first-child { display: flex; flex-direction: column; min-width: 180px; }.workbench-toolbar .el-input { width: 280px; margin-left: auto; }.workbench-grid { height: calc(100% - 104px); display: grid; grid-template-columns: 230px minmax(500px,1fr) 300px; }.workbench-page.has-batch-progress .workbench-grid { height: calc(100% - 184px); }.batch-progress-float { min-height: 80px; display: grid; grid-template-columns: 210px minmax(250px,1fr) auto auto; align-items: center; gap: 18px; padding: 10px 18px; border-bottom: 1px solid var(--ink); background: var(--masthead); box-shadow: 0 8px 18px rgba(0,0,0,.14); position: relative; z-index: 9; }.batch-progress-float::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 5px; background: var(--signal); }.batch-progress-float.completed::before { background: var(--good); }.batch-progress-float.failed::before,.batch-progress-float.partial::before { background: var(--bad); }.batch-progress-title { display: flex; flex-direction: column; gap: 2px; }.batch-progress-title>span { color: var(--signal); font: 700 8px monospace; letter-spacing: .1em; }.batch-progress-title>b { font-size: 13px; }.batch-progress-title>small { color: var(--muted); font-size: 9px; }.batch-progress-bar>div { display: flex; justify-content: space-between; margin-bottom: 6px; }.batch-progress-bar b { font-size: 11px; }.batch-progress-bar span { color: var(--muted); font-size: 9px; }.batch-progress-bar :deep(.el-progress-bar__inner) { background: var(--signal); }.batch-progress-float.completed .batch-progress-bar :deep(.el-progress-bar__inner) { background: var(--good); }.batch-progress-metrics { display: flex; gap: 11px; }.batch-progress-metrics span { color: var(--muted); font-size: 8px; text-align: center; white-space: nowrap; }.batch-progress-metrics b { display: block; color: var(--ink); font: 800 16px Rockwell,serif; }.batch-progress-metrics .bad,.batch-progress-metrics .bad b { color: var(--bad); }.batch-progress-metrics .cooldown,.batch-progress-metrics .cooldown b { color: var(--warn); }.batch-progress-actions { min-width: 126px; display: flex; flex-direction: column; align-items: stretch; gap: 3px; }.batch-progress-actions .el-button+.el-button { margin-left: 0; }.batch-progress-actions small { color: var(--warn); font-size: 7px; text-align: center; }
.question-list { border-right: 1px solid var(--ink); overflow-y: auto; background: var(--paper-deep); }.question-list button { width: 100%; min-height: 64px; display: grid; grid-template-columns: 42px 1fr; grid-template-rows: 1fr auto; text-align: left; border: 0; border-bottom: 1px solid var(--line); color: var(--ink); background: transparent; padding: 11px; }.question-list button>b { grid-row: 1/3; font: 800 18px Rockwell,serif; color: var(--muted); }.question-list button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.question-list button i { font-style: normal; font-size: 10px; color: var(--muted); }.question-list button i.good { color: var(--good); }.question-list button i.warn { color: var(--warn); }.question-list button i.bad { color: var(--bad); }.question-list button:hover,.question-list button.active { background: var(--panel); }.question-list button.active { border-left: 5px solid var(--signal); padding-left: 6px; }
.canvas { min-width: 0; overflow-y: auto; padding: 20px; background: var(--panel); }.canvas>header { display: flex; align-items: baseline; gap: 12px; border-bottom: 1px solid var(--line); padding-bottom: 14px; }.canvas>header>span { font: 800 13px monospace; color: var(--signal); }.canvas>header h2 { margin: 0; font: 800 24px Rockwell,"FZYaoti",serif; }.canvas>header em { margin-left: auto; font-style: normal; font-size: 12px; color: var(--muted); }.image-columns { display: grid; grid-template-columns: 1fr 42px 1fr; min-height: 500px; padding-top: 18px; }.stage-label { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }.stage-label b { font: 800 11px monospace; }.stage-label span { font-size: 10px; color: var(--muted); }.dependency-arrow { display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--signal); }.dependency-arrow b { font-size: 28px; }.dependency-arrow span { writing-mode: vertical-rl; font-size: 9px; letter-spacing: .14em; }.image-stage.locked { opacity: .65; }.candidate-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }.candidate-grid article { position: relative; aspect-ratio: 4/3; border: 1px solid var(--line); background: var(--image-well); overflow: hidden; }.candidate-grid article.selected { outline: 3px solid var(--good); outline-offset: -3px; }.candidate-grid article.stale { filter: grayscale(1); opacity: .58; }.candidate-grid img { width: 100%; height: 100%; object-fit: contain; display: block; }.candidate-grid article>span { position: absolute; top: 6px; left: 6px; background: var(--solid); color: var(--on-solid); padding: 3px 5px; font: 700 9px monospace; }.candidate-grid article>em { position: absolute; bottom: 6px; left: 6px; padding: 4px 6px; color: var(--on-solid); background: var(--overlay); font: 7px monospace; font-style: normal; }.candidate-grid article>b,.candidate-grid article>button { position: absolute; bottom: 6px; right: 6px; border: 0; padding: 6px 8px; background: var(--good); color: white; font-size: 10px; }.candidate-grid article>button { background: var(--signal); }.image-empty { min-height: 310px; border: 1px dashed var(--line); display: grid; place-content: center; text-align: center; }.image-empty>span { font: 900 90px/.8 Rockwell,serif; color: var(--paper-deep); }.image-empty p { color: var(--muted); line-height: 1.7; font-size: 12px; }.reference-chip { display: flex; align-items: center; gap: 8px; padding: 6px; border: 1px solid var(--line); margin-bottom: 8px; font-size: 9px; color: var(--muted); }.reference-chip img { width: 36px; height: 28px; object-fit: contain; }
.prompt-panel { border-left: 1px solid var(--ink); background: var(--paper-deep); overflow-y: auto; padding: 15px; }.panel-heading { display: flex; flex-direction: column; border-bottom: 1px solid var(--ink); padding-bottom: 12px; }.panel-heading span { font: 700 9px monospace; color: var(--signal); }.panel-heading b { margin-top: 5px; }.prompt-block { margin: 15px 0; }.prompt-block label { font-size: 10px; font-weight: 800; color: var(--muted); }.prompt-block p,details pre { font: 12px/1.65 "Microsoft YaHei",sans-serif; white-space: pre-wrap; max-height: 155px; overflow: auto; }.prompt-block.suffix { padding: 10px; background: var(--panel); }.prompt-block.suffix p { color: var(--cyan); }.prompt-panel summary { font-size: 11px; color: var(--signal); cursor: pointer; }.prompt-panel pre { padding: 8px; background: var(--solid); color: var(--on-solid); }.rule { border-top: 1px solid var(--ink); margin: 20px 0; }
.settings-jump { position: sticky; top: 88px; z-index: 8; display: grid; grid-template-columns: repeat(4,1fr); gap: 1px; margin: -10px 0 22px; border: 1px solid var(--ink); background: var(--line); box-shadow: 6px 6px 0 var(--paper-deep); }.settings-jump button { border: 0; padding: 12px 14px; color: var(--ink); background: var(--panel); text-align: left; font-weight: 800; cursor: pointer; }.settings-jump button:hover { color: var(--signal); background: var(--surface-hover); }.settings-jump span { margin-right: 10px; color: var(--signal); font: 700 9px monospace; }
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }.settings-card { scroll-margin-top: 145px; border: 1px solid var(--ink); background: var(--panel); padding: 24px; box-shadow: 8px 8px 0 var(--paper-deep); }.settings-card.full-card { grid-column: 1/-1; }.settings-card header { display: flex; gap: 14px; border-bottom: 1px solid var(--line); margin-bottom: 20px; padding-bottom: 18px; }.settings-card header>span { flex: 0 0 34px; width: 34px; height: 34px; display: grid; place-items: center; color: var(--on-solid); background: var(--solid); font: 800 18px Rockwell,serif; }.settings-card h2 { margin: 0; font: 800 22px Rockwell,"FZYaoti",serif; }.settings-card header p { margin: 5px 0; color: var(--muted); font-size: 12px; }.settings-card>label,.inline-fields label,.candidate-defaults label,.prompt-fields label { display: flex; justify-content: space-between; margin: 17px 0 7px; font-size: 11px; font-weight: 800; }.settings-card label em { font-weight: 400; color: var(--muted); }.settings-card>.el-button { margin-top: 20px; }.inline-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.service-mode { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 18px; }.service-mode button { min-height: 62px; padding: 10px 14px; border: 1px solid var(--line); color: var(--ink); background: var(--paper); text-align: left; cursor: pointer; }.service-mode button b,.service-mode button span { display: block; }.service-mode button span { margin-top: 4px; color: var(--muted); font-size: 10px; }.service-mode button.active { border: 2px solid var(--signal); padding: 9px 13px; background: var(--surface-warm); color: var(--signal); }.saved-services { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 12px; border: 1px dashed var(--line); background: var(--paper-deep); }.saved-services>span { margin-right: 5px; color: var(--muted); font: 700 9px monospace; }.saved-services button { border: 1px solid var(--line); padding: 7px 10px; color: var(--ink); background: var(--panel); font-size: 10px; }.saved-services button i { display: block; color: var(--muted); font-size: 8px; font-style: normal; }.saved-services button.active { border-color: var(--signal); color: var(--signal); }
.official-links { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin: 14px 0; }.official-links a { padding: 11px 12px; border: 1px solid var(--ink); color: var(--ink); background: var(--paper); text-decoration: none; }.official-links a:hover { transform: translateY(-2px); border-color: var(--signal); }.official-links b,.official-links span { display: block; }.official-links b { font-size: 11px; }.official-links span { margin-top: 4px; color: var(--signal); font-size: 9px; }
.retry-card { margin: 18px 0; padding: 14px; border: 1px solid var(--bad); background: var(--surface-danger); }.retry-card>b { color: var(--bad); font-size: 12px; }.retry-card .failure-message { margin: 8px 0; color: var(--ink); font: 700 11px/1.55 monospace; word-break: break-word; }.failure-advice { margin: 10px 0; padding: 10px; border-left: 3px solid var(--warn); background: var(--surface-control); }.failure-advice span { color: var(--warn); font: 700 9px monospace; }.failure-advice p { margin: 5px 0 0; font-size: 10px; line-height: 1.65; color: var(--muted); }.failure-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }.failure-actions .el-button+.el-button { margin-left: 0; }.failure-actions a { color: var(--signal); font-size: 9px; }
.advanced-controls { margin: 18px 0; padding: 16px; border: 1px solid var(--line); background: repeating-linear-gradient(135deg,var(--paper-deep),var(--paper-deep) 8px,var(--surface-control) 8px,var(--surface-control) 16px); }.advanced-title { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }.advanced-title span { color: var(--signal); font: 700 9px monospace; letter-spacing: .14em; }.advanced-title b { font-size: 13px; }.advanced-controls p { margin: 10px 0 0; color: var(--muted); font-size: 9px; line-height: 1.5; }.advanced-controls .inline-fields { align-items: end; }.control-label { display: block; margin: 12px 0 7px; font-size: 10px; font-weight: 800; }.ratio-presets { display: grid; grid-template-columns: repeat(5,1fr); gap: 6px; }.ratio-presets button { min-height: 76px; border: 1px solid var(--line); color: var(--ink); background: var(--surface-control); cursor: pointer; }.ratio-presets button b,.ratio-presets button span,.ratio-presets button i,.ratio-presets button small { display: block; }.ratio-presets button b { font: 800 15px Rockwell,serif; }.ratio-presets button span { font-size: 9px; }.ratio-presets button i { margin-top: 4px; color: var(--muted); font: 8px monospace; }.ratio-presets button small { margin-top: 3px; color: var(--good); font-size: 7px; }.ratio-presets button.active { border: 2px solid var(--signal); color: var(--signal); background: var(--surface-hover); }
.guidance-control { margin: 16px 0 8px; padding: 14px 16px 10px; border: 1px solid var(--ink); background: var(--surface-control); }.guidance-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.guidance-heading>div { display: flex; flex-direction: column; gap: 3px; }.guidance-heading label { font-size: 11px; font-weight: 800; }.guidance-heading span { color: var(--signal); font-size: 9px; }.guidance-control :deep(.el-switch) { --el-switch-on-color: var(--signal); min-width: 82px; }.guidance-control :deep(.el-slider) { margin: 18px 0 28px; }.guidance-note { display: grid; grid-template-columns: auto 1fr auto 1fr auto; align-items: center; gap: 7px; padding-top: 8px; border-top: 1px dashed var(--line); font-size: 9px; }.guidance-note b { color: var(--signal); }.guidance-note span { color: var(--muted); }.guidance-note button { border: 0; color: var(--signal); background: transparent; cursor: pointer; font-size: 9px; }.provider-default-note { display: flex; gap: 9px; margin-top: 12px; padding: 10px; border-left: 3px solid var(--good); background: var(--paper-deep); font-size: 9px; }.provider-default-note b { color: var(--good); }.provider-default-note span { color: var(--muted); }
.single-output-switch { display: flex; align-items: center; gap: 16px; padding: 16px; border: 1px solid var(--ink); background: var(--paper-deep); }.single-output-switch b { font-size: 14px; }.single-output-switch p { margin: 4px 0 0; color: var(--muted); font-size: 10px; }.candidate-defaults { display: grid; grid-template-columns: 220px 220px 1fr; align-items: end; gap: 16px; }.candidate-defaults.disabled { opacity: .58; }.candidate-defaults p { margin: 0 0 6px; color: var(--muted); font-size: 10px; line-height: 1.6; }
.quota-status-strip { display: grid; grid-template-columns: auto auto minmax(240px,1fr) auto auto; align-items: center; gap: 10px; padding: 12px 14px; background: var(--solid); color: var(--on-solid); }.quota-status-strip>b { color: var(--on-solid); font: 900 28px Rockwell,serif; }.quota-status-strip>span { color: var(--muted); font-size: 9px; }.quota-status-strip>p { margin: 0; padding-left: 12px; border-left: 1px solid var(--line); font-size: 9px; line-height: 1.5; }.quota-status-strip>a { color: #ffbf8c; font-size: 9px; }.quota-cards { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; margin-top: 12px; }.quota-cards>article { padding: 14px; border: 1px solid var(--line); background: var(--paper); }.quota-cards>article.exhausted,.quota-cards>article.invalid,.quota-cards>article.disabled { border-left: 5px solid var(--bad); }.quota-card-head { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: start; }.quota-card-head b,.quota-card-head span { display: block; }.quota-card-head span { margin-top: 3px; color: var(--muted); font-size: 9px; }.quota-card-head em { font: 10px monospace; font-style: normal; }.quota-card-head small { color: var(--good); }.quota-progress { margin-top: 13px; }.quota-progress.unknown :deep(.el-progress-bar__inner) { background: var(--line); }.quota-progress>div { display: flex; justify-content: space-between; gap: 10px; margin-top: 7px; }.quota-progress b { font-size: 10px; }.quota-progress span { color: var(--muted); font-size: 9px; }.quota-cards article>p { margin: 9px 0 0; color: var(--muted); font-size: 9px; }.quota-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 10px; }.quota-actions button,.credential-editor-title button { border: 0; color: var(--signal); background: transparent; font-size: 9px; cursor: pointer; }.quota-actions button.danger { color: var(--bad); }.key-empty { padding: 24px; border: 1px dashed var(--line); text-align: center; background: var(--paper-deep); }.key-empty.compact { min-height: 130px; display: grid; place-content: center; }.key-empty p { color: var(--muted); font-size: 11px; }
.credential-add { scroll-margin-top: 150px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; margin-top: 14px; padding: 16px; border-top: 3px solid var(--signal); background: var(--paper-deep); }.credential-editor-title { grid-column: 1/-1; display: flex; justify-content: space-between; }.credential-add label { display: block; margin: 0 0 5px; font-size: 9px; font-weight: 800; }.credential-add .key-field { grid-column: 1/-1; }.credential-add>.el-checkbox { align-self: center; }.prompt-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }.global-settings-note { margin: 18px 0 0; padding: 11px 13px; border-left: 4px solid var(--good); color: var(--muted); background: var(--paper-deep); font-size: 11px; line-height: 1.65; }.global-settings-note b { margin-right: 8px; color: var(--good); }
.export-summary { border: 1px solid var(--ink); background: var(--panel); padding: 20px; display: grid; grid-template-columns: 220px 1fr auto; align-items: center; }.export-summary div span { display: block; font-size: 10px; color: var(--muted); }.export-summary div b { font: 900 48px Rockwell,serif; }.export-summary div em { font-style: normal; color: var(--muted); }.export-summary code { background: var(--paper-deep); padding: 3px; }.final-pairs { margin-top: 22px; display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }.final-pairs article { display: grid; grid-template: auto 1fr / 1fr 1fr; gap: 1px; background: var(--solid); border: 1px solid var(--ink); }.final-pairs header { grid-column: 1/-1; background: var(--panel); padding: 10px; display: flex; gap: 8px; }.final-pairs article>div { aspect-ratio: 4/3; position: relative; background: var(--paper-deep); }.final-pairs img { width: 100%; height: 100%; object-fit: contain; }.final-pairs i { position: absolute; bottom: 5px; right: 5px; color: var(--on-solid); background: var(--solid); font-style: normal; font: 9px monospace; padding: 3px; }.export-result { margin-top: 24px; border-left: 8px solid var(--good); background: var(--panel); padding: 18px; }.export-result b { color: var(--good); }.export-result p { font-family: monospace; word-break: break-all; }.export-result span { margin-right: 20px; }
.range-form label { display: block; font-size: 11px; font-weight: 800; margin-bottom: 6px; }.range-summary { display: grid; grid-template-columns: auto auto auto 1fr; align-items: baseline; gap: 7px; padding: 15px 18px; color: var(--on-solid); background: var(--solid); }.range-summary>span { color: var(--muted); font: 700 9px monospace; }.range-summary>b { color: var(--on-solid); font: 900 30px Rockwell,serif; }.range-summary>em { color: var(--muted); font-size: 10px; font-style: normal; }.range-summary>p { margin: 0; text-align: right; font-size: 10px; }.range-summary i { padding: 0 6px; color: var(--signal); font-style: normal; }.range-slider-shell { margin: 14px 0 8px; padding: 14px 24px 22px; border: 1px solid var(--line); background: var(--paper-deep); }.range-slider-heading { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 4px; }.range-slider-heading b { font-size: 11px; }.range-slider-heading span { color: var(--muted); font-size: 9px; }.range-slider-shell :deep(.el-slider) { margin: 22px 0 8px; }.range-presets { display: flex; gap: 6px; margin-bottom: 16px; }.range-presets button { padding: 7px 10px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; font-size: 9px; }.range-presets button:hover { border-color: var(--signal); color: var(--signal); }.range-codes { display: grid; grid-template-columns: 1fr auto 1fr; align-items: end; gap: 12px; margin-bottom: 20px; }.range-codes>b { padding-bottom: 8px; color: var(--signal); }.range-codes .el-select { width: 100%; }.candidate-counts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 16px 0 20px; }.candidate-counts.disabled { opacity: .5; }.parallelism-control { margin: 8px 0 22px; padding: 14px 22px 18px; border: 1px solid var(--ink); background: var(--surface-control); }.parallelism-control>div { display: flex; justify-content: space-between; }.parallelism-control b { font-size: 11px; }.parallelism-control span,.parallelism-control p { color: var(--muted); font-size: 9px; }.parallelism-control :deep(.el-slider) { margin: 22px 0 18px; }.parallelism-control p { margin: 0; line-height: 1.5; }.quota-ticket { border: 1px solid var(--ink); background: var(--paper-deep); padding: 18px; }.quota-ticket>span { font: 700 9px monospace; color: var(--signal); }.quota-ticket>div { display: flex; align-items: baseline; gap: 8px; margin: 12px 0; }.quota-ticket>div b { font: 800 32px Rockwell,serif; }.quota-ticket>div i { font-style: normal; font-size: 10px; color: var(--muted); margin-right: 12px; }.quota-ticket p { font-size: 13px; }.quota-ticket small { display: block; color: var(--warn); line-height: 1.5; margin-bottom: 12px; }.quota-ticket .range-preflight { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; margin: 12px 0; padding: 10px; border: 1px solid var(--good); background: rgba(34,160,107,.06); }.quota-ticket .range-preflight.blocked { border-color: var(--bad); background: rgba(181,52,52,.06); }.range-preflight>b { color: var(--good); font-size: 11px; }.range-preflight.blocked>b { color: var(--bad); }.range-preflight>p { margin: 0; font-size: 9px; line-height: 1.5; }.range-preflight>a { color: var(--signal); font-size: 9px; }
@media (max-width: 1280px) { .workbench-grid { grid-template-columns: 200px minmax(480px,1fr) 270px; }.page { padding: 28px; }.project-grid { grid-template-columns: repeat(2,1fr); }.final-pairs { grid-template-columns: repeat(3,1fr); }.candidate-defaults { grid-template-columns: 190px 190px 1fr; }.quota-status-strip { grid-template-columns: auto auto 1fr auto; }.quota-status-strip>.el-button { grid-column: 4; }.quota-status-strip>a { grid-column: 3; }.batch-progress-float { grid-template-columns: 176px minmax(190px,1fr) auto 86px; gap: 10px; padding: 10px 12px; }.batch-progress-metrics { gap: 6px; }.batch-progress-metrics span { font-size: 7px; }.batch-progress-metrics b { font-size: 14px; } }
@media (max-width: 900px) { .settings-jump { grid-template-columns: 1fr 1fr; }.official-links,.ratio-presets { grid-template-columns: 1fr 1fr; }.candidate-defaults,.quota-cards,.prompt-fields { grid-template-columns: 1fr; }.candidate-defaults p { margin-top: 8px; }.quota-status-strip { grid-template-columns: auto auto 1fr; }.quota-status-strip>a,.quota-status-strip>.el-button { grid-column: 3; }.credential-add { grid-template-columns: 1fr; }.credential-add>* { grid-column: 1!important; } }
.range-form { max-height: 78vh; overflow-y: auto; padding-right: 5px; }
.about-grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 20px; }.about-grid>article,.repository-card { border: 1px solid var(--ink); background: var(--panel); box-shadow: 8px 8px 0 var(--paper-deep); padding: 26px; }.about-intro { grid-row: span 2; display: flex; flex-direction: column; }.about-intro>span,.repository-card>span,.storage-card header>span,.cache-card>span { color: var(--signal); font: 800 11px monospace; letter-spacing: .13em; }.about-intro h2 { margin: 30px 0 16px; max-width: 740px; font: 800 clamp(30px,3.3vw,54px)/1.08 Rockwell,"FZYaoti",serif; }.about-intro>p { max-width: 720px; color: var(--muted); font-size: 14px; line-height: 1.9; }.about-version { margin-top: auto; padding-top: 28px; border-top: 1px solid var(--line); display: grid; grid-template-columns: auto auto 1fr; align-items: baseline; gap: 12px; }.about-version b { color: var(--signal); font: 800 11px monospace; }.about-version strong { font: 900 38px Rockwell,serif; }.about-version em { color: var(--muted); font-style: normal; }.repository-card { position: relative; display: block; min-height: 180px; color: var(--on-solid); background: var(--solid); text-decoration: none; }.repository-card b { display: block; margin-top: 25px; font: 800 26px Rockwell,serif; }.repository-card p { color: var(--muted); font-size: 12px; }.repository-card i { position: absolute; right: 22px; bottom: 18px; color: var(--signal); font: 900 34px Rockwell,serif; font-style: normal; }.repository-card:hover { transform: translate(-2px,-2px); box-shadow: 12px 12px 0 var(--paper-deep); }.storage-card { grid-column: 1/-1; }.storage-card header { display: flex; align-items: baseline; gap: 18px; border-bottom: 1px solid var(--line); padding-bottom: 16px; }.storage-card h2 { margin: 0; font: 800 25px Rockwell,"FZYaoti",serif; }.storage-card>div { display: grid; grid-template-columns: 90px 1fr; gap: 12px; align-items: start; margin-top: 16px; }.storage-card b { font-size: 12px; }.storage-card code { padding: 8px 10px; color: var(--cyan); background: var(--paper-deep); word-break: break-all; font-size: 12px; }.storage-card p,.cache-card p { color: var(--muted); font-size: 12px; line-height: 1.7; }.cache-card>div { display: flex; align-items: baseline; gap: 9px; margin: 24px 0 12px; }.cache-card>div b { font: 900 42px Rockwell,serif; }.cache-card>div em { color: var(--muted); font-style: normal; }.cache-card>div strong { margin-left: auto; color: var(--cyan); font: 800 18px monospace; }
.brand-mark i,.brand small,.rail button span,.batch-progress-title>span,.batch-progress-metrics span,.batch-progress-actions small,.candidate-grid article>em,.ratio-presets button small { font-size: 10px; }.theme-toggle b,.project-switch em,.serial,.stage-label span,.question-list button i,.prompt-block label,.service-mode button span,.saved-services button,.official-links span,.control-label,.single-output-switch p,.quota-progress b,.export-summary div span,.range-summary>em,.range-summary>p { font-size: 11px; }.batch-progress-title>small,.batch-progress-bar span,.dependency-arrow span,.candidate-grid article>span,.reference-chip,.panel-heading span,.saved-services>span,.saved-services button i,.failure-advice span,.failure-actions a,.advanced-title span,.advanced-controls p,.ratio-presets button span,.ratio-presets button i,.guidance-heading span,.guidance-note,.provider-default-note,.quota-status-strip>span,.quota-status-strip>p,.quota-status-strip>a,.quota-card-head span,.quota-card-head em,.quota-progress span,.quota-cards article>p,.quota-actions button,.credential-editor-title button,.credential-add label,.range-summary>span,.range-slider-heading span,.range-presets button,.parallelism-control span,.parallelism-control p,.quota-ticket>span,.range-preflight>p,.range-preflight>a { font-size: 10px; line-height: 1.45; }
.output-location-strip { height: 44px; display: grid; grid-template-columns: auto auto minmax(180px,1fr) auto; align-items: center; gap: 10px; padding: 6px 16px; border-bottom: 1px solid var(--line); background: var(--paper-deep); }.output-location-strip>span { color: var(--signal); font: 800 10px monospace; letter-spacing: .1em; }.output-location-strip>b { font-size: 11px; }.output-location-strip>code { overflow: hidden; color: var(--cyan); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.output-location-strip .el-button { min-height: 30px; }
.support-level-note { display: flex; gap: 12px; margin: 10px 0 14px; padding: 11px 13px; border-left: 4px solid var(--warn); background: var(--paper-deep); }.support-level-note.optimized { border-color: var(--good); }.support-level-note b { color: var(--warn); font-size: 12px; white-space: nowrap; }.support-level-note.optimized b { color: var(--good); }.support-level-note span { color: var(--muted); font-size: 11px; line-height: 1.55; }
.api-mode-panel { margin: 18px 0; padding: 16px; border: 1px solid var(--ink); background: var(--surface-control); }.api-mode-options { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 13px; }.api-mode-options button { padding: 13px 14px; border: 1px solid var(--line); color: var(--ink); background: var(--panel); text-align: left; cursor: pointer; }.api-mode-options button.active { border: 2px solid var(--signal); padding: 12px 13px; box-shadow: 4px 4px 0 var(--paper-deep); }.api-mode-options b,.api-mode-options span { display: block; }.api-mode-options b { font-size: 13px; }.api-mode-options span { margin-top: 4px; color: var(--muted); font-size: 11px; }.api-endpoint-preview { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: center; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--line); background: var(--paper-deep); }.api-endpoint-preview.agent_plan { border-color: var(--signal); }.api-endpoint-preview span { color: var(--signal); font: 800 10px monospace; }.api-endpoint-preview code { overflow-wrap: anywhere; color: var(--cyan); font-size: 11px; }.api-mode-warning,.api-mode-standard-note { margin: 10px 0 0; font-size: 11px; line-height: 1.6; }.api-mode-warning { padding: 10px 12px; border-left: 4px solid var(--warn); color: var(--muted); background: rgba(211,132,24,.08); }.api-mode-warning b { color: var(--warn); }.api-mode-warning code { color: var(--signal); }.api-mode-standard-note { color: var(--muted); }
.storage-card>.storage-actions { display: flex; grid-template-columns: none; gap: 10px; }.storage-actions .el-button { margin: 0; }
@media (max-width: 1100px) { .about-grid { grid-template-columns: 1fr; }.about-intro { grid-row: auto; min-height: 430px; }.storage-card { grid-column: auto; }.output-location-strip { grid-template-columns: auto minmax(160px,1fr) auto; }.output-location-strip>b { display: none; } }
</style>
