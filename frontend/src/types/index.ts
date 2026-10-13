export type Status = 'idle' | 'loading' | 'success' | 'error'

export interface PaginationParams {
  page: number
  page_size: number
}

export interface SelectOption {
  label: string
  value: string
}
