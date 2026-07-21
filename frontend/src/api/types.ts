export interface Project {
  id: string
  name: string
  question_count?: number
  workspace_path?: string
  candidate_images_directory?: string
  exports_directory?: string
  q1_prompt_suffix?: string
  q2_prompt_suffix?: string
  selected_provider_profile_id?: string | null
}

export interface ModelInfo {
  provider: string
  model: string
  display_name: string
  max_text_outputs: number
  max_edit_outputs: number
  default_size: string
  multiple_output_semantics: 'exact' | 'maximum'
  unit_price_cny: string
  price_checked_on: string
  documentation_url?: string
  api_key_url?: string
  provider_console_url?: string
  agent_plan_api_key_url?: string
  agent_plan_documentation_url?: string
  support_level: 'optimized' | 'testing'
}

export interface ProviderProfile {
  id: string
  project_id: string
  provider: string
  display_name: string
  base_url: string
  workspace_id?: string
  model_id: string
  secret_configured: boolean
  last_four?: string
  remember_secret: boolean
  session_only?: boolean
  config: Record<string, unknown>
  credentials: ProviderCredential[]
}

export interface ProviderCredential {
  id: string
  profile_id: string
  label: string
  account_label: string
  priority: number
  enabled: boolean
  secret_configured: boolean
  last_four?: string
  remember_secret: boolean
  status: 'active' | 'cooldown' | 'exhausted' | 'invalid' | 'disabled'
  manual_remaining_images?: number | null
  cooldown_until?: string | null
  failure_count: number
  last_error_safe?: string | null
  session_only?: boolean
  local_generated_images?: number
  local_estimated_cost_cny?: string
  preflight_status?: 'ok' | 'failed' | 'not_checked' | 'unavailable'
  preflight_message?: string
}

export interface QuotaStatus {
  profile_id: string
  provider: string
  model_id: string
  checked_at: string
  supports_non_billable_preflight: boolean
  available_credential_count: number
  official_quota: {
    kind: 'console_only' | 'shared_account_model' | 'unknown'
    note: string
    console_url: string
  }
  credentials: ProviderCredential[]
}

export interface ImageAsset {
  id: string
  stage: 'image1' | 'image2'
  output_index: number
  url: string
  selected: boolean
  stale: boolean
  reference_asset_id?: string
  width: number
  height: number
}

export interface Question {
  id: string
  code: string
  title: string
  answer: string
  state: string
  priority_blind_test: boolean
  image1_prompt: string
  image2_prompt: string
  selected_image1_id?: string
  selected_image2_id?: string
  latest_failed_task_id?: string | null
  latest_error?: string | null
  latest_error_category?: string | null
  assets: ImageAsset[]
}

export interface ImportPreview {
  token: string
  source_name: string
  recognized_count: number
  complete_count: number
  warning_count: number
  error_count: number
  questions: Array<{ code: string; title: string; answer: string; priority_blind_test: boolean }>
  issues: Array<{ severity: string; code: string; message: string; question_code?: string }>
}

export interface Estimate {
  question_count: number
  image1_maximum: number
  image2_maximum: number
  total_maximum: number
  estimated_cost_cny: string
  actual_may_be_lower: boolean
  price_checked_on: string
  unit_price_cny: string
}

export interface BatchProgress {
  id: string
  status: 'draft' | 'confirmed' | 'running' | 'waiting_review' | 'completed' | 'partial' | 'failed' | 'paused' | 'cancelled'
  start_code: string
  end_code: string
  question_count: number
  completed_question_count: number
  review_question_count: number
  failed_question_count: number
  completed_stage_count: number
  expected_stage_count: number
  progress_percent: number
  running_task_count: number
  queued_task_count: number
  retry_waiting_count: number
  next_retry_at: string | null
  interrupted_task_count: number
  can_pause: boolean
  can_resume: boolean
  scheduler_parallelism: number
  scheduler_active_count: number
  scheduler_queued_count: number
  scheduler_delayed_count: number
  scheduler_held_count: number
  runs: Array<{
    id: string
    question_id: string
    stage: 'image1' | 'image2'
    status: string
    requested_outputs: number
  }>
}

export interface SystemInfo {
  name: string
  version: string
  description: string
  repository_url: string
  data_directory: string
  projects_directory: string
  cache_directory: string
  cache_file_count: number
  cache_bytes: number
}
