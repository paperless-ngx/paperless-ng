import { Observable } from 'rxjs'
import { AsnPrefix } from './asn-prefix'
import { Correspondent } from './correspondent'
import { CustomFieldInstance } from './custom-field-instance'
import { DocumentNote } from './document-note'
import { DocumentType } from './document-type'
import { ObjectWithPermissions } from './object-with-permissions'
import { StoragePath } from './storage-path'
import { Tag } from './tag'

export enum DisplayMode {
  TABLE = 'table',
  SMALL_CARDS = 'smallCards',
  LARGE_CARDS = 'largeCards',
}

export enum DisplayField {
  TITLE = 'title',
  CREATED = 'created',
  ADDED = 'added',
  TAGS = 'tag',
  CORRESPONDENT = 'correspondent',
  DOCUMENT_TYPE = 'documenttype',
  STORAGE_PATH = 'storagepath',
  CUSTOM_FIELD = 'custom_field_',
  NOTES = 'note',
  OWNER = 'owner',
  SHARED = 'shared',
  ASN = 'asn',
  PAGE_COUNT = 'pagecount',
}

export const DEFAULT_DISPLAY_FIELDS = [
  {
    id: DisplayField.TITLE,
    name: $localize`Title`,
  },
  {
    id: DisplayField.CREATED,
    name: $localize`Created`,
  },
  {
    id: DisplayField.ADDED,
    name: $localize`Added`,
  },
  {
    id: DisplayField.TAGS,
    name: $localize`Tags`,
  },
  {
    id: DisplayField.CORRESPONDENT,
    name: $localize`Correspondent`,
  },
  {
    id: DisplayField.DOCUMENT_TYPE,
    name: $localize`Document type`,
  },
  {
    id: DisplayField.STORAGE_PATH,
    name: $localize`Storage path`,
  },
  {
    id: DisplayField.NOTES,
    name: $localize`Notes`,
  },
  {
    id: DisplayField.OWNER,
    name: $localize`Owner`,
  },
  {
    id: DisplayField.SHARED,
    name: $localize`Shared`,
  },
  {
    id: DisplayField.ASN,
    name: $localize`ASN`,
  },
  {
    id: DisplayField.PAGE_COUNT,
    name: $localize`Pages`,
  },
]

export const DEFAULT_DASHBOARD_VIEW_PAGE_SIZE = 10

export const DEFAULT_DASHBOARD_DISPLAY_FIELDS = [
  DisplayField.CREATED,
  DisplayField.TITLE,
  DisplayField.TAGS,
  DisplayField.CORRESPONDENT,
]

export const DOCUMENT_SORT_FIELDS = [
  { field: 'archive_serial_number', name: $localize`ASN` },
  { field: 'correspondent__name', name: $localize`Correspondent` },
  { field: 'title', name: $localize`Title` },
  { field: 'document_type__name', name: $localize`Document type` },
  { field: 'created', name: $localize`Created` },
  { field: 'added', name: $localize`Added` },
  { field: 'modified', name: $localize`Modified` },
  { field: 'num_notes', name: $localize`Notes` },
  { field: 'owner', name: $localize`Owner` },
  { field: 'page_count', name: $localize`Pages` },
]

export const DOCUMENT_SORT_FIELDS_FULLTEXT = [
  {
    field: 'score',
    name: $localize`:Score is a value returned by the full text search engine and specifies how well a result matches the given query:Search score`,
  },
]

export interface SearchHit {
  score?: number
  rank?: number

  highlights?: string
  note_highlights?: string
}

export interface Document extends ObjectWithPermissions {
  archive_serial_number_prefix$?: Observable<AsnPrefix>

  archive_serial_number_prefix?: number

  correspondent$?: Observable<Correspondent>

  correspondent?: number

  document_type$?: Observable<DocumentType>

  document_type?: number

  storage_path$?: Observable<StoragePath>

  storage_path?: number

  title?: string

  content?: string

  tags$?: Observable<Tag[]>

  tags?: number[]

  checksum?: string

  // UTC
  created?: Date

  // localized date
  created_date?: Date

  modified?: Date

  added?: Date

  mime_type?: string

  deleted_at?: Date

  original_file_name?: string

  archived_file_name?: string

  download_url?: string

  thumbnail_url?: string

  archive_serial_number?: number

  notes?: DocumentNote[]

  __search_hit__?: SearchHit

  custom_fields?: CustomFieldInstance[]

  // write-only field
  remove_inbox_tags?: boolean

  page_count?: number
}
