import type { Question } from '../api/types'

export function isExportPending(question: Pick<
  Question,
  | 'state'
  | 'selected_image1_id'
  | 'selected_image2_id'
  | 'last_exported_image1_id'
  | 'last_exported_image2_id'
>): boolean {
  return question.state === 'completed'
    && Boolean(question.selected_image1_id)
    && Boolean(question.selected_image2_id)
    && (
      question.selected_image1_id !== question.last_exported_image1_id
      || question.selected_image2_id !== question.last_exported_image2_id
    )
}
