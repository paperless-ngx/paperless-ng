import { HttpClient } from '@angular/common/http'
import { Injectable } from '@angular/core'
import { Observable } from 'rxjs'
import { map, tap } from 'rxjs/operators'
import { AuditLogEntry } from 'src/app/data/auditlog-entry'
import { CustomField } from 'src/app/data/custom-field'
import {
  DOCUMENT_SORT_FIELDS,
  DOCUMENT_SORT_FIELDS_FULLTEXT,
  Document,
} from 'src/app/data/document'
import { DocumentMetadata } from 'src/app/data/document-metadata'
import { DocumentSuggestions } from 'src/app/data/document-suggestions'
import { FilterRule } from 'src/app/data/filter-rule'
import { Results } from 'src/app/data/results'
import { SETTINGS_KEYS } from 'src/app/data/ui-settings'
import { queryParamsFromFilterRules } from '../../utils/query-params'
import {
  PermissionAction,
  PermissionType,
  PermissionsService,
} from '../permissions.service'
import { SettingsService } from '../settings.service'
import { AbstractPaperlessService } from './abstract-paperless-service'
import { CorrespondentService } from './correspondent.service'
import { CustomFieldsService } from './custom-fields.service'
import { DocumentTypeService } from './document-type.service'
import { StoragePathService } from './storage-path.service'
import { TagService } from './tag.service'

export interface SelectionDataItem {
  id: number
  document_count: number
}

export interface SelectionData {
  selected_storage_paths: SelectionDataItem[]
  selected_correspondents: SelectionDataItem[]
  selected_tags: SelectionDataItem[]
  selected_document_types: SelectionDataItem[]
  selected_custom_fields: SelectionDataItem[]
}

@Injectable({
  providedIn: 'root',
})
export class DocumentService extends AbstractPaperlessService<Document> {
  private _searchQuery: string

  private _sortFields
  get sortFields() {
    return this._sortFields
  }

  private _sortFieldsFullText
  get sortFieldsFullText() {
    return this._sortFieldsFullText
  }

  private customFields: CustomField[] = []

  constructor(
    http: HttpClient,
    private correspondentService: CorrespondentService,
    private documentTypeService: DocumentTypeService,
    private tagService: TagService,
    private storagePathService: StoragePathService,
    private permissionsService: PermissionsService,
    private settingsService: SettingsService,
    private customFieldService: CustomFieldsService
  ) {
    super(http, 'documents')
    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.CustomField
      )
    ) {
      this.customFieldService.listAll().subscribe((fields) => {
        this.customFields = fields.results
        this.setupSortFields()
      })
    }

    this.setupSortFields()
  }

  private setupSortFields() {
    this._sortFields = [...DOCUMENT_SORT_FIELDS]
    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.CustomField
      )
    ) {
      this.customFields.forEach((field) => {
        this._sortFields.push({
          field: `custom_field_${field.id}`,
          name: field.name,
        })
      })
    }
    let excludes = []
    if (
      !this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.Correspondent
      )
    ) {
      excludes.push('correspondent__name')
    }
    if (
      !this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.DocumentType
      )
    ) {
      excludes.push('document_type__name')
    }
    if (
      !this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.User
      )
    ) {
      excludes.push('owner')
    }
    if (!this.settingsService.get(SETTINGS_KEYS.NOTES_ENABLED)) {
      excludes.push('num_notes')
    }
    this._sortFields = this._sortFields.filter(
      (field) => !excludes.includes(field.field)
    )
    this._sortFieldsFullText = [
      ...this._sortFields,
      ...DOCUMENT_SORT_FIELDS_FULLTEXT,
    ]
  }

  addObservablesToDocument(doc: Document) {
    if (
      doc.correspondent &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.Correspondent
      )
    ) {
      doc.correspondent$ = this.correspondentService.getCached(
        doc.correspondent
      )
    }
    if (
      doc.document_type &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.DocumentType
      )
    ) {
      doc.document_type$ = this.documentTypeService.getCached(doc.document_type)
    }
    if (
      doc.tags &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.Tag
      )
    ) {
      doc.tags$ = this.tagService
        .getCachedMany(doc.tags)
        .pipe(
          tap((tags) =>
            tags.sort((tagA, tagB) => tagA.name.localeCompare(tagB.name))
          )
        )
    }
    if (
      doc.storage_path &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.StoragePath
      )
    ) {
      doc.storage_path$ = this.storagePathService.getCached(doc.storage_path)
    }
    return doc
  }

  listFiltered(
    page?: number,
    pageSize?: number,
    sortField?: string,
    sortReverse?: boolean,
    filterRules?: FilterRule[],
    extraParams = {}
  ): Observable<Results<Document>> {
    return this.list(
      page,
      pageSize,
      sortField,
      sortReverse,
      Object.assign(extraParams, queryParamsFromFilterRules(filterRules))
    ).pipe(
      map((results) => {
        results.results.forEach((doc) => this.addObservablesToDocument(doc))
        return results
      })
    )
  }

  listAllFilteredIds(filterRules?: FilterRule[]): Observable<number[]> {
    return this.listFiltered(1, 100000, null, null, filterRules, {
      fields: 'id',
    }).pipe(map((response) => response.results.map((doc) => doc.id)))
  }

  get(id: number): Observable<Document> {
    return this.http.get<Document>(this.getResourceUrl(id), {
      params: {
        full_perms: true,
      },
    })
  }

  getPreviewUrl(id: number, original: boolean = false): string {
    let url = this.getResourceUrl(id, 'preview')
    if (this._searchQuery) url += `#search="${this._searchQuery}"`
    if (original) {
      url += '?original=true'
    }
    return url
  }

  getThumbUrl(id: number): string {
    return this.getResourceUrl(id, 'thumb')
  }

  getDownloadUrl(id: number, original: boolean = false): string {
    let url = this.getResourceUrl(id, 'download')
    if (original) {
      url += '?original=true'
    }
    return url
  }

  getNextAsn(): Observable<number> {
    return this.http.get<number>(this.getResourceUrl(null, 'next_asn'))
  }

  update(o: Document): Observable<Document> {
    // we want to only set created_date
    o.created = undefined
    o.remove_inbox_tags = !!this.settingsService.get(
      SETTINGS_KEYS.DOCUMENT_EDITING_REMOVE_INBOX_TAGS
    )
    return super.update(o)
  }

  uploadDocument(formData) {
    return this.http.post(
      this.getResourceUrl(null, 'post_document'),
      formData,
      { reportProgress: true, observe: 'events' }
    )
  }

  getMetadata(id: number): Observable<DocumentMetadata> {
    return this.http.get<DocumentMetadata>(this.getResourceUrl(id, 'metadata'))
  }

  bulkEdit(ids: number[], method: string, args: any) {
    return this.http.post(this.getResourceUrl(null, 'bulk_edit'), {
      documents: ids,
      method: method,
      parameters: args,
    })
  }

  getSelectionData(ids: number[]): Observable<SelectionData> {
    return this.http.post<SelectionData>(
      this.getResourceUrl(null, 'selection_data'),
      { documents: ids }
    )
  }

  getSuggestions(id: number): Observable<DocumentSuggestions> {
    return this.http.get<DocumentSuggestions>(
      this.getResourceUrl(id, 'suggestions')
    )
  }

  getHistory(id: number): Observable<AuditLogEntry[]> {
    return this.http.get<AuditLogEntry[]>(this.getResourceUrl(id, 'history'))
  }

  bulkDownload(
    ids: number[],
    content = 'both',
    useFilenameFormatting: boolean = false
  ) {
    return this.http.post(
      this.getResourceUrl(null, 'bulk_download'),
      {
        documents: ids,
        content: content,
        follow_formatting: useFilenameFormatting,
      },
      { responseType: 'blob' }
    )
  }

  public set searchQuery(query: string) {
    this._searchQuery = query
  }

  emailDocument(
    documentId: number,
    addresses: string,
    subject: string,
    message: string,
    useArchiveVersion: boolean
  ): Observable<any> {
    return this.http.post(this.getResourceUrl(documentId, 'email'), {
      addresses: addresses,
      subject: subject,
      message: message,
      use_archive_version: useArchiveVersion,
    })
  }
}
