import { AsyncPipe, NgTemplateOutlet } from '@angular/common'
import { HttpClient } from '@angular/common/http'
import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core'
import {
  FormArray,
  FormControl,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms'
import { ActivatedRoute, Router } from '@angular/router'
import {
  NgbDateStruct,
  NgbDropdownModule,
  NgbModal,
  NgbNav,
  NgbNavChangeEvent,
  NgbNavModule,
} from '@ng-bootstrap/ng-bootstrap'
import { dirtyCheck, DirtyComponent } from '@ngneat/dirty-check-forms'
import { PDFDocumentProxy, PdfViewerModule } from 'ng2-pdf-viewer'
import { NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import { BehaviorSubject, Observable, Subject } from 'rxjs'
import {
  debounceTime,
  distinctUntilChanged,
  filter,
  first,
  map,
  switchMap,
  takeUntil,
} from 'rxjs/operators'
import { Correspondent } from 'src/app/data/correspondent'
import { CustomField, CustomFieldDataType } from 'src/app/data/custom-field'
import { CustomFieldInstance } from 'src/app/data/custom-field-instance'
import { DataType } from 'src/app/data/datatype'
import { Document } from 'src/app/data/document'
import { DocumentMetadata } from 'src/app/data/document-metadata'
import { DocumentNote } from 'src/app/data/document-note'
import { DocumentSuggestions } from 'src/app/data/document-suggestions'
import { DocumentType } from 'src/app/data/document-type'
import { FilterRule } from 'src/app/data/filter-rule'
import {
  FILTER_CORRESPONDENT,
  FILTER_CREATED_AFTER,
  FILTER_CREATED_BEFORE,
  FILTER_DOCUMENT_TYPE,
  FILTER_FULLTEXT_MORELIKE,
  FILTER_HAS_TAGS_ALL,
  FILTER_STORAGE_PATH,
} from 'src/app/data/filter-rule-type'
import { ObjectWithId } from 'src/app/data/object-with-id'
import { StoragePath } from 'src/app/data/storage-path'
import { Tag } from 'src/app/data/tag'
import { SETTINGS_KEYS } from 'src/app/data/ui-settings'
import { User } from 'src/app/data/user'
import { IfPermissionsDirective } from 'src/app/directives/if-permissions.directive'
import { CustomDatePipe } from 'src/app/pipes/custom-date.pipe'
import { DocumentTitlePipe } from 'src/app/pipes/document-title.pipe'
import { FileSizePipe } from 'src/app/pipes/file-size.pipe'
import { SafeUrlPipe } from 'src/app/pipes/safeurl.pipe'
import { DocumentListViewService } from 'src/app/services/document-list-view.service'
import { HotKeyService } from 'src/app/services/hot-key.service'
import { OpenDocumentsService } from 'src/app/services/open-documents.service'
import {
  PermissionAction,
  PermissionsService,
  PermissionType,
} from 'src/app/services/permissions.service'
import { CorrespondentService } from 'src/app/services/rest/correspondent.service'
import { CustomFieldsService } from 'src/app/services/rest/custom-fields.service'
import { DocumentTypeService } from 'src/app/services/rest/document-type.service'
import { DocumentService } from 'src/app/services/rest/document.service'
import { StoragePathService } from 'src/app/services/rest/storage-path.service'
import { UserService } from 'src/app/services/rest/user.service'
import { SettingsService } from 'src/app/services/settings.service'
import { ToastService } from 'src/app/services/toast.service'
import { ISODateAdapter } from 'src/app/utils/ngb-iso-date-adapter'
import * as UTIF from 'utif'
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component'
import { DeletePagesConfirmDialogComponent } from '../common/confirm-dialog/delete-pages-confirm-dialog/delete-pages-confirm-dialog.component'
import { RotateConfirmDialogComponent } from '../common/confirm-dialog/rotate-confirm-dialog/rotate-confirm-dialog.component'
import { SplitConfirmDialogComponent } from '../common/confirm-dialog/split-confirm-dialog/split-confirm-dialog.component'
import { CustomFieldsDropdownComponent } from '../common/custom-fields-dropdown/custom-fields-dropdown.component'
import { CorrespondentEditDialogComponent } from '../common/edit-dialog/correspondent-edit-dialog/correspondent-edit-dialog.component'
import { DocumentTypeEditDialogComponent } from '../common/edit-dialog/document-type-edit-dialog/document-type-edit-dialog.component'
import { EditDialogMode } from '../common/edit-dialog/edit-dialog.component'
import { StoragePathEditDialogComponent } from '../common/edit-dialog/storage-path-edit-dialog/storage-path-edit-dialog.component'
import { CheckComponent } from '../common/input/check/check.component'
import { DateComponent } from '../common/input/date/date.component'
import { DocumentLinkComponent } from '../common/input/document-link/document-link.component'
import { MonetaryComponent } from '../common/input/monetary/monetary.component'
import { NumberComponent } from '../common/input/number/number.component'
import { PermissionsFormComponent } from '../common/input/permissions/permissions-form/permissions-form.component'
import { SelectComponent } from '../common/input/select/select.component'
import { TagsComponent } from '../common/input/tags/tags.component'
import { TextComponent } from '../common/input/text/text.component'
import { UrlComponent } from '../common/input/url/url.component'
import { PageHeaderComponent } from '../common/page-header/page-header.component'
import { ShareDocumentDropdownComponent } from '../common/share-document-dropdown/share-document-dropdown.component'
import { DocumentHistoryComponent } from '../document-history/document-history.component'
import { DocumentNotesComponent } from '../document-notes/document-notes.component'
import { ComponentWithPermissions } from '../with-permissions/with-permissions.component'
import { MetadataCollapseComponent } from './metadata-collapse/metadata-collapse.component'

enum DocumentDetailNavIDs {
  Details = 1,
  Content = 2,
  Metadata = 3,
  Preview = 4,
  Notes = 5,
  Permissions = 6,
  History = 7,
}

enum ContentRenderType {
  PDF = 'pdf',
  Image = 'image',
  Text = 'text',
  Other = 'other',
  Unknown = 'unknown',
  TIFF = 'tiff',
}

enum ZoomSetting {
  PageFit = 'page-fit',
  PageWidth = 'page-width',
  Quarter = '.25',
  Half = '.5',
  ThreeQuarters = '.75',
  One = '1',
  OneAndHalf = '1.5',
  Two = '2',
  Three = '3',
}

@Component({
  selector: 'pngx-document-detail',
  templateUrl: './document-detail.component.html',
  styleUrls: ['./document-detail.component.scss'],
  imports: [
    PageHeaderComponent,
    CustomFieldsDropdownComponent,
    DocumentNotesComponent,
    DocumentHistoryComponent,
    ShareDocumentDropdownComponent,
    CheckComponent,
    DateComponent,
    DocumentLinkComponent,
    MetadataCollapseComponent,
    PermissionsFormComponent,
    SelectComponent,
    TagsComponent,
    TextComponent,
    NumberComponent,
    MonetaryComponent,
    UrlComponent,
    CustomDatePipe,
    FileSizePipe,
    IfPermissionsDirective,
    AsyncPipe,
    FormsModule,
    ReactiveFormsModule,
    NgTemplateOutlet,
    SafeUrlPipe,
    NgbNavModule,
    NgbDropdownModule,
    NgxBootstrapIconsModule,
    PdfViewerModule,
  ],
})
export class DocumentDetailComponent
  extends ComponentWithPermissions
  implements OnInit, OnDestroy, DirtyComponent
{
  @ViewChild('inputTitle')
  titleInput: TextComponent

  expandOriginalMetadata = false
  expandArchivedMetadata = false

  error: any

  networkActive = false

  documentId: number
  document: Document
  metadata: DocumentMetadata
  suggestions: DocumentSuggestions
  users: User[]

  title: string
  titleSubject: Subject<string> = new Subject()
  previewUrl: string
  thumbUrl: string
  previewText: string
  downloadUrl: string
  downloadOriginalUrl: string
  previewLoaded: boolean = false
  tiffURL: string
  tiffError: string

  correspondents: Correspondent[]
  documentTypes: DocumentType[]
  storagePaths: StoragePath[]

  documentForm: FormGroup = new FormGroup({
    title: new FormControl(''),
    content: new FormControl(''),
    created_date: new FormControl(),
    correspondent: new FormControl(),
    document_type: new FormControl(),
    storage_path: new FormControl(),
    archive_serial_number: new FormControl(),
    tags: new FormControl([]),
    permissions_form: new FormControl(null),
    custom_fields: new FormArray([]),
  })

  previewCurrentPage: number = 1
  previewNumPages: number
  previewZoomSetting: ZoomSetting = ZoomSetting.One
  previewZoomScale: ZoomSetting = ZoomSetting.PageWidth

  store: BehaviorSubject<any>
  isDirty$: Observable<boolean>
  unsubscribeNotifier: Subject<any> = new Subject()
  docChangeNotifier: Subject<any> = new Subject()

  requiresPassword: boolean = false
  password: string

  ogDate: Date

  customFields: CustomField[]
  public readonly CustomFieldDataType = CustomFieldDataType

  public readonly ContentRenderType = ContentRenderType

  public readonly DataType = DataType

  @ViewChild('nav') nav: NgbNav
  @ViewChild('pdfPreview') set pdfPreview(element) {
    // this gets called when component added or removed from DOM
    if (
      element &&
      element.nativeElement.offsetParent !== null &&
      this.nav?.activeId == 4
    ) {
      // its visible
      setTimeout(() => this.nav?.select(1))
    }
  }

  DocumentDetailNavIDs = DocumentDetailNavIDs
  activeNavID: number

  constructor(
    private documentsService: DocumentService,
    private route: ActivatedRoute,
    private correspondentService: CorrespondentService,
    private documentTypeService: DocumentTypeService,
    private router: Router,
    private modalService: NgbModal,
    private openDocumentService: OpenDocumentsService,
    private documentListViewService: DocumentListViewService,
    private documentTitlePipe: DocumentTitlePipe,
    private toastService: ToastService,
    private settings: SettingsService,
    private storagePathService: StoragePathService,
    private permissionsService: PermissionsService,
    private userService: UserService,
    private customFieldsService: CustomFieldsService,
    private http: HttpClient,
    private hotKeyService: HotKeyService
  ) {
    super()
  }

  titleKeyUp(event) {
    this.titleSubject.next(event.target?.value)
  }

  get useNativePdfViewer(): boolean {
    return this.settings.get(SETTINGS_KEYS.USE_NATIVE_PDF_VIEWER)
  }

  get archiveContentRenderType(): ContentRenderType {
    return this.document?.archived_file_name
      ? this.getRenderType('application/pdf')
      : this.getRenderType(this.document?.mime_type)
  }

  get originalContentRenderType(): ContentRenderType {
    return this.getRenderType(this.document?.mime_type)
  }

  get showThumbnailOverlay(): boolean {
    return this.settings.get(SETTINGS_KEYS.DOCUMENT_EDITING_OVERLAY_THUMBNAIL)
  }

  private getRenderType(mimeType: string): ContentRenderType {
    if (!mimeType) return ContentRenderType.Unknown
    if (mimeType === 'application/pdf') {
      return ContentRenderType.PDF
    } else if (
      ['text/plain', 'application/csv', 'text/csv'].includes(mimeType)
    ) {
      return ContentRenderType.Text
    } else if (mimeType.indexOf('tiff') >= 0) {
      return ContentRenderType.TIFF
    } else if (mimeType?.indexOf('image/') === 0) {
      return ContentRenderType.Image
    }
    return ContentRenderType.Other
  }

  get isRTL() {
    if (!this.metadata || !this.metadata.lang) return false
    else {
      return ['ar', 'he', 'fe'].includes(this.metadata.lang)
    }
  }

  ngOnInit(): void {
    this.documentForm.valueChanges
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        this.error = null
        const docValues = Object.assign({}, this.documentForm.value)
        docValues['owner'] =
          this.documentForm.get('permissions_form').value['owner']
        docValues['set_permissions'] =
          this.documentForm.get('permissions_form').value['set_permissions']
        delete docValues['permissions_form']
        Object.assign(this.document, docValues)
      })

    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.Correspondent
      )
    ) {
      this.correspondentService
        .listAll()
        .pipe(first(), takeUntil(this.unsubscribeNotifier))
        .subscribe((result) => (this.correspondents = result.results))
    }
    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.DocumentType
      )
    ) {
      this.documentTypeService
        .listAll()
        .pipe(first(), takeUntil(this.unsubscribeNotifier))
        .subscribe((result) => (this.documentTypes = result.results))
    }
    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.StoragePath
      )
    ) {
      this.storagePathService
        .listAll()
        .pipe(first(), takeUntil(this.unsubscribeNotifier))
        .subscribe((result) => (this.storagePaths = result.results))
    }
    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.User
      )
    ) {
      this.userService
        .listAll()
        .pipe(first(), takeUntil(this.unsubscribeNotifier))
        .subscribe((result) => (this.users = result.results))
    }

    this.getCustomFields()

    this.route.paramMap
      .pipe(
        filter((paramMap) => {
          // only init when changing docs & section is set
          return (
            +paramMap.get('id') !== this.documentId &&
            paramMap.get('section')?.length > 0
          )
        }),
        takeUntil(this.unsubscribeNotifier),
        switchMap((paramMap) => {
          const documentId = +paramMap.get('id')
          this.docChangeNotifier.next(documentId)
          // Dont wait to get the preview
          this.previewUrl = this.documentsService.getPreviewUrl(documentId)
          this.http.get(this.previewUrl, { responseType: 'text' }).subscribe({
            next: (res) => {
              this.previewText = res.toString()
            },
            error: (err) => {
              this.previewText = $localize`An error occurred loading content: ${
                err.message ?? err.toString()
              }`
            },
          })
          this.thumbUrl = this.documentsService.getThumbUrl(documentId)
          return this.documentsService.get(documentId)
        })
      )
      .pipe(
        switchMap((doc) => {
          this.documentId = doc.id
          this.downloadUrl = this.documentsService.getDownloadUrl(
            this.documentId
          )
          this.downloadOriginalUrl = this.documentsService.getDownloadUrl(
            this.documentId,
            true
          )
          this.suggestions = null
          const openDocument = this.openDocumentService.getOpenDocument(
            this.documentId
          )

          if (openDocument) {
            if (
              new Date(doc.modified) > new Date(openDocument.modified) &&
              !this.modalService.hasOpenModals()
            ) {
              let modal = this.modalService.open(ConfirmDialogComponent)
              modal.componentInstance.title = $localize`Document changes detected`
              modal.componentInstance.messageBold = $localize`The version of this document in your browser session appears older than the existing version.`
              modal.componentInstance.message = $localize`Saving the document here may overwrite other changes that were made. To restore the existing version, discard your changes or close the document.`
              modal.componentInstance.cancelBtnClass = 'visually-hidden'
              modal.componentInstance.btnCaption = $localize`Ok`
              modal.componentInstance.confirmClicked.subscribe(() =>
                modal.close()
              )
            }

            if (this.documentForm.dirty) {
              Object.assign(openDocument, this.documentForm.value)
              openDocument['owner'] =
                this.documentForm.get('permissions_form').value['owner']
              openDocument['permissions'] =
                this.documentForm.get('permissions_form').value[
                  'set_permissions'
                ]
              delete openDocument['permissions_form']
            }
            this.updateComponent(openDocument)
          } else {
            this.openDocumentService.openDocument(doc)
            this.updateComponent(doc)
          }

          this.titleSubject
            .pipe(
              debounceTime(1000),
              distinctUntilChanged(),
              takeUntil(this.docChangeNotifier),
              takeUntil(this.unsubscribeNotifier)
            )
            .subscribe({
              next: (titleValue) => {
                // In the rare case when the field changed just after debounced event was fired.
                // We dont want to overwrite what's actually in the text field, so just return
                if (titleValue !== this.titleInput.value) return

                this.title = titleValue
                this.documentForm.patchValue({ title: titleValue })
              },
              complete: () => {
                // doc changed so we manually check dirty in case title was changed
                if (
                  this.store.getValue().title !==
                  this.documentForm.get('title').value
                ) {
                  this.openDocumentService.setDirty(doc, true)
                }
              },
            })

          // Initialize dirtyCheck
          this.store = new BehaviorSubject({
            title: doc.title,
            content: doc.content,
            created_date: doc.created_date,
            correspondent: doc.correspondent,
            document_type: doc.document_type,
            storage_path: doc.storage_path,
            archive_serial_number: doc.archive_serial_number,
            tags: [...doc.tags],
            permissions_form: {
              owner: doc.owner,
              set_permissions: doc.permissions,
            },
            custom_fields: [...doc.custom_fields],
          })

          this.isDirty$ = dirtyCheck(
            this.documentForm,
            this.store.asObservable()
          )

          return this.isDirty$.pipe(
            takeUntil(this.unsubscribeNotifier),
            map((dirty) => ({ doc, dirty }))
          )
        })
      )
      .subscribe({
        next: ({ doc, dirty }) => {
          this.openDocumentService.setDirty(doc, dirty)
        },
        error: (error) => {
          this.router.navigate(['404'], {
            replaceUrl: true,
          })
        },
      })

    this.route.paramMap.subscribe((paramMap) => {
      const section = paramMap.get('section')
      if (section) {
        const navIDKey: string = Object.keys(DocumentDetailNavIDs).find(
          (navID) => navID.toLowerCase() == section
        )
        if (navIDKey) {
          this.activeNavID = DocumentDetailNavIDs[navIDKey]
        }
      } else if (paramMap.get('id')) {
        this.router.navigate(['documents', +paramMap.get('id'), 'details'], {
          replaceUrl: true,
        })
      }
    })

    this.hotKeyService
      .addShortcut({
        keys: 'control.arrowright',
        description: $localize`Next document`,
      })
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        if (this.hasNext()) this.nextDoc()
      })

    this.hotKeyService
      .addShortcut({
        keys: 'control.arrowleft',
        description: $localize`Previous document`,
      })
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        if (this.hasPrevious()) this.previousDoc()
      })

    this.hotKeyService
      .addShortcut({ keys: 'escape', description: $localize`Close document` })
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        this.close()
      })

    this.hotKeyService
      .addShortcut({ keys: 'control.s', description: $localize`Save document` })
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        if (this.openDocumentService.isDirty(this.document)) this.save()
      })

    this.hotKeyService
      .addShortcut({
        keys: 'control.shift.s',
        description: $localize`Save and close / next`,
      })
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        if (this.openDocumentService.isDirty(this.document)) this.saveEditNext()
      })
  }

  ngOnDestroy(): void {
    this.unsubscribeNotifier.next(this)
    this.unsubscribeNotifier.complete()
  }

  onNavChange(navChangeEvent: NgbNavChangeEvent) {
    const [foundNavIDkey] = Object.entries(DocumentDetailNavIDs).find(
      ([, navIDValue]) => navIDValue == navChangeEvent.nextId
    )
    if (foundNavIDkey)
      this.router.navigate([
        'documents',
        this.documentId,
        foundNavIDkey.toLowerCase(),
      ])
  }

  updateComponent(doc: Document) {
    this.document = doc
    this.requiresPassword = false
    this.updateFormForCustomFields()
    if (this.archiveContentRenderType === ContentRenderType.TIFF) {
      this.tryRenderTiff()
    }
    this.documentsService
      .getMetadata(doc.id)
      .pipe(
        first(),
        takeUntil(this.unsubscribeNotifier),
        takeUntil(this.docChangeNotifier)
      )
      .subscribe({
        next: (result) => {
          this.metadata = result
          if (
            this.archiveContentRenderType !== ContentRenderType.PDF ||
            this.useNativePdfViewer
          ) {
            this.previewLoaded = true
          }
        },
        error: (error) => {
          this.metadata = {} // allow display to fallback to <object> tag
          this.toastService.showError(
            $localize`Error retrieving metadata`,
            error
          )
        },
      })
    if (
      this.permissionsService.currentUserHasObjectPermissions(
        PermissionAction.Change,
        doc
      ) &&
      this.permissionsService.currentUserCan(
        PermissionAction.Change,
        PermissionType.Document
      )
    ) {
      this.documentsService
        .getSuggestions(doc.id)
        .pipe(
          first(),
          takeUntil(this.unsubscribeNotifier),
          takeUntil(this.docChangeNotifier)
        )
        .subscribe({
          next: (result) => {
            this.suggestions = result
          },
          error: (error) => {
            this.suggestions = null
            this.toastService.showError(
              $localize`Error retrieving suggestions.`,
              error
            )
          },
        })
    }
    this.title = this.documentTitlePipe.transform(doc.title)
    const docFormValues = Object.assign({}, doc)
    docFormValues['permissions_form'] = {
      owner: doc.owner,
      set_permissions: doc.permissions,
    }

    this.documentForm.patchValue(docFormValues, { emitEvent: false })
    if (!this.userCanEdit) this.documentForm.disable()
  }

  get customFieldFormFields(): FormArray {
    return this.documentForm.get('custom_fields') as FormArray
  }

  createDocumentType(newName: string) {
    var modal = this.modalService.open(DocumentTypeEditDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.dialogMode = EditDialogMode.CREATE
    if (newName) modal.componentInstance.object = { name: newName }
    modal.componentInstance.succeeded
      .pipe(
        switchMap((newDocumentType) => {
          return this.documentTypeService
            .listAll()
            .pipe(map((documentTypes) => ({ newDocumentType, documentTypes })))
        })
      )
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(({ newDocumentType, documentTypes }) => {
        this.documentTypes = documentTypes.results
        this.documentForm.get('document_type').setValue(newDocumentType.id)
      })
  }

  createCorrespondent(newName: string) {
    var modal = this.modalService.open(CorrespondentEditDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.dialogMode = EditDialogMode.CREATE
    if (newName) modal.componentInstance.object = { name: newName }
    modal.componentInstance.succeeded
      .pipe(
        switchMap((newCorrespondent) => {
          return this.correspondentService
            .listAll()
            .pipe(
              map((correspondents) => ({ newCorrespondent, correspondents }))
            )
        })
      )
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(({ newCorrespondent, correspondents }) => {
        this.correspondents = correspondents.results
        this.documentForm.get('correspondent').setValue(newCorrespondent.id)
      })
  }

  createStoragePath(newName: string) {
    var modal = this.modalService.open(StoragePathEditDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.dialogMode = EditDialogMode.CREATE
    if (newName) modal.componentInstance.object = { name: newName }
    modal.componentInstance.succeeded
      .pipe(
        switchMap((newStoragePath) => {
          return this.storagePathService
            .listAll()
            .pipe(map((storagePaths) => ({ newStoragePath, storagePaths })))
        })
      )
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(({ newStoragePath, storagePaths }) => {
        this.storagePaths = storagePaths.results
        this.documentForm.get('storage_path').setValue(newStoragePath.id)
      })
  }

  createDisabled(dataType: DataType) {
    switch (dataType) {
      case DataType.Correspondent:
        return !this.permissionsService.currentUserCan(
          PermissionAction.Add,
          PermissionType.Correspondent
        )
      case DataType.DocumentType:
        return !this.permissionsService.currentUserCan(
          PermissionAction.Add,
          PermissionType.DocumentType
        )
      case DataType.StoragePath:
        return !this.permissionsService.currentUserCan(
          PermissionAction.Add,
          PermissionType.StoragePath
        )
      case DataType.Tag:
        return !this.permissionsService.currentUserCan(
          PermissionAction.Add,
          PermissionType.Tag
        )
    }
  }

  discard() {
    this.documentsService
      .get(this.documentId)
      .pipe(first())
      .subscribe({
        next: (doc) => {
          Object.assign(this.document, doc)
          doc['permissions_form'] = {
            owner: doc.owner,
            set_permissions: doc.permissions,
          }
          this.title = doc.title
          this.updateFormForCustomFields()
          this.documentForm.patchValue(doc)
          this.openDocumentService.setDirty(doc, false)
        },
        error: () => {
          this.router.navigate(['404'], {
            replaceUrl: true,
          })
        },
      })
  }

  save(close: boolean = false) {
    this.networkActive = true
    ;(document.activeElement as HTMLElement)?.dispatchEvent(new Event('change'))
    this.documentsService
      .update(this.document)
      .pipe(first())
      .subscribe({
        next: (docValues) => {
          // in case data changed while saving eg removing inbox_tags
          this.documentForm.patchValue(docValues)
          const newValues = Object.assign({}, this.documentForm.value)
          newValues.tags = [...docValues.tags]
          newValues.custom_fields = [...docValues.custom_fields]
          this.store.next(newValues)
          this.openDocumentService.setDirty(this.document, false)
          this.openDocumentService.save()
          this.toastService.showInfo($localize`Document saved successfully.`)
          this.networkActive = false
          this.error = null
          if (close) {
            this.close(() =>
              this.openDocumentService.refreshDocument(this.documentId)
            )
          } else {
            this.openDocumentService.refreshDocument(this.documentId)
          }
        },
        error: (error) => {
          this.networkActive = false
          if (!this.userCanEdit) {
            this.toastService.showInfo($localize`Document saved successfully.`)
            close && this.close()
          } else {
            this.error = error.error
            this.toastService.showError($localize`Error saving document`, error)
          }
        },
      })
  }

  saveEditNext() {
    this.networkActive = true
    this.store.next(this.documentForm.value)
    this.documentsService
      .update(this.document)
      .pipe(
        switchMap((updateResult) => {
          return this.documentListViewService
            .getNext(this.documentId)
            .pipe(map((nextDocId) => ({ nextDocId, updateResult })))
        })
      )
      .pipe(
        switchMap(({ nextDocId, updateResult }) => {
          if (nextDocId && updateResult)
            return this.openDocumentService
              .closeDocument(this.document)
              .pipe(
                map((closeResult) => ({ updateResult, nextDocId, closeResult }))
              )
        })
      )
      .pipe(first())
      .subscribe({
        next: ({ updateResult, nextDocId, closeResult }) => {
          this.error = null
          this.networkActive = false
          if (closeResult && updateResult && nextDocId) {
            this.router.navigate(['documents', nextDocId])
            this.titleInput?.focus()
          }
        },
        error: (error) => {
          this.networkActive = false
          this.error = error.error
          this.toastService.showError($localize`Error saving document`, error)
        },
      })
  }

  close(closedCallback: () => void = null) {
    this.openDocumentService
      .closeDocument(this.document)
      .pipe(first())
      .subscribe((closed) => {
        if (!closed) return
        if (closedCallback) closedCallback()
        if (this.documentListViewService.activeSavedViewId) {
          this.router.navigate([
            'view',
            this.documentListViewService.activeSavedViewId,
          ])
        } else {
          this.router.navigate(['documents'])
        }
      })
  }

  delete() {
    let modal = this.modalService.open(ConfirmDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.title = $localize`Confirm`
    modal.componentInstance.messageBold = $localize`Do you really want to move the document "${this.document.title}" to the trash?`
    modal.componentInstance.message = $localize`Documents can be restored prior to permanent deletion.`
    modal.componentInstance.btnClass = 'btn-danger'
    modal.componentInstance.btnCaption = $localize`Move to trash`
    this.subscribeModalDelete(modal) // so can be re-subscribed if error
  }

  subscribeModalDelete(modal) {
    modal.componentInstance.confirmClicked
      .pipe(
        switchMap(() => {
          modal.componentInstance.buttonsEnabled = false
          return this.documentsService.delete(this.document)
        })
      )
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe({
        next: () => {
          modal.close()
          this.close()
        },
        error: (error) => {
          this.toastService.showError($localize`Error deleting document`, error)
          modal.componentInstance.buttonsEnabled = true
          this.subscribeModalDelete(modal)
        },
      })
  }

  moreLike() {
    this.documentListViewService.quickFilter([
      {
        rule_type: FILTER_FULLTEXT_MORELIKE,
        value: this.documentId.toString(),
      },
    ])
  }

  reprocess() {
    let modal = this.modalService.open(ConfirmDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.title = $localize`Reprocess confirm`
    modal.componentInstance.messageBold = $localize`This operation will permanently recreate the archive file for this document.`
    modal.componentInstance.message = $localize`The archive file will be re-generated with the current settings.`
    modal.componentInstance.btnClass = 'btn-danger'
    modal.componentInstance.btnCaption = $localize`Proceed`
    modal.componentInstance.confirmClicked.subscribe(() => {
      modal.componentInstance.buttonsEnabled = false
      this.documentsService
        .bulkEdit([this.document.id], 'reprocess', {})
        .subscribe({
          next: () => {
            this.toastService.showInfo(
              $localize`Reprocess operation will begin in the background. Close and re-open or reload this document after the operation has completed to see new content.`
            )
            if (modal) {
              modal.close()
            }
          },
          error: (error) => {
            if (modal) {
              modal.componentInstance.buttonsEnabled = true
            }
            this.toastService.showError(
              $localize`Error executing operation`,
              error
            )
          },
        })
    })
  }

  hasNext() {
    return this.documentListViewService.hasNext(this.documentId)
  }

  hasPrevious() {
    return this.documentListViewService.hasPrevious(this.documentId)
  }

  nextDoc() {
    this.documentListViewService
      .getNext(this.document.id)
      .subscribe((nextDocId: number) => {
        this.router.navigate(['documents', nextDocId])
      })
  }

  previousDoc() {
    this.documentListViewService
      .getPrevious(this.document.id)
      .subscribe((prevDocId: number) => {
        this.router.navigate(['documents', prevDocId])
      })
  }

  pdfPreviewLoaded(pdf: PDFDocumentProxy) {
    this.previewNumPages = pdf.numPages
    if (this.password) this.requiresPassword = false
    setTimeout(() => {
      this.previewLoaded = true
    }, 300)
  }

  onError(event) {
    if (event.name == 'PasswordException') {
      this.requiresPassword = true
      this.previewLoaded = true
    }
  }

  onPasswordKeyUp(event: KeyboardEvent) {
    if ('Enter' == event.key) {
      this.password = (event.target as HTMLInputElement).value
    }
  }

  onZoomSelect(event: Event) {
    const setting = (event.target as HTMLSelectElement)?.value as ZoomSetting
    if (ZoomSetting.PageFit === setting) {
      this.previewZoomSetting = ZoomSetting.One
      this.previewZoomScale = setting
    } else {
      this.previewZoomScale = ZoomSetting.PageWidth
      this.previewZoomSetting = setting
    }
  }

  get zoomSettings() {
    return Object.values(ZoomSetting).filter(
      (setting) => setting !== ZoomSetting.PageWidth
    )
  }

  getZoomSettingTitle(setting: ZoomSetting): string {
    switch (setting) {
      case ZoomSetting.PageFit:
        return $localize`Page Fit`
      default:
        return `${parseFloat(setting) * 100}%`
    }
  }

  increaseZoom(): void {
    let currentIndex = Object.values(ZoomSetting).indexOf(
      this.previewZoomSetting
    )
    if (this.previewZoomScale === ZoomSetting.PageFit) currentIndex = 5
    this.previewZoomScale = ZoomSetting.PageWidth
    this.previewZoomSetting =
      Object.values(ZoomSetting)[
        Math.min(Object.values(ZoomSetting).length - 1, currentIndex + 1)
      ]
  }

  decreaseZoom(): void {
    let currentIndex = Object.values(ZoomSetting).indexOf(
      this.previewZoomSetting
    )
    if (this.previewZoomScale === ZoomSetting.PageFit) currentIndex = 4
    this.previewZoomScale = ZoomSetting.PageWidth
    this.previewZoomSetting =
      Object.values(ZoomSetting)[Math.max(2, currentIndex - 1)]
  }

  get showPermissions(): boolean {
    return (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.User
      ) && this.userIsOwner
    )
  }

  get notesEnabled(): boolean {
    return (
      this.settings.get(SETTINGS_KEYS.NOTES_ENABLED) &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.Note
      )
    )
  }

  get historyEnabled(): boolean {
    return (
      this.settings.get(SETTINGS_KEYS.AUDITLOG_ENABLED) &&
      this.userIsOwner &&
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.History
      )
    )
  }

  notesUpdated(notes: DocumentNote[]) {
    this.document.notes = notes
    this.openDocumentService.refreshDocument(this.documentId)
  }

  get userIsOwner(): boolean {
    let doc: Document = Object.assign({}, this.document)
    // dont disable while editing
    if (
      this.document &&
      this.store?.value.permissions_form?.hasOwnProperty('owner')
    ) {
      doc.owner = this.store.value.permissions_form.owner
    }
    return !this.document || this.permissionsService.currentUserOwnsObject(doc)
  }

  get userCanEdit(): boolean {
    let doc: Document = Object.assign({}, this.document)
    // dont disable while editing
    if (
      this.document &&
      this.store?.value.permissions_form?.hasOwnProperty('owner')
    ) {
      doc.owner = this.store.value.permissions_form.owner
    }
    return (
      !this.document ||
      (this.permissionsService.currentUserCan(
        PermissionAction.Change,
        PermissionType.Document
      ) &&
        this.permissionsService.currentUserHasObjectPermissions(
          PermissionAction.Change,
          doc
        ))
    )
  }

  get userCanAdd(): boolean {
    return this.permissionsService.currentUserCan(
      PermissionAction.Add,
      PermissionType.Document
    )
  }

  filterDocuments(items: ObjectWithId[] | NgbDateStruct[], type?: DataType) {
    const filterRules: FilterRule[] = items.flatMap((i) => {
      if (i.hasOwnProperty('year')) {
        const isoDateAdapter = new ISODateAdapter()
        const dateAfter: Date = new Date(isoDateAdapter.toModel(i))
        dateAfter.setDate(dateAfter.getDate() - 1)
        const dateBefore: Date = new Date(isoDateAdapter.toModel(i))
        dateBefore.setDate(dateBefore.getDate() + 1)
        // Created Date
        return [
          {
            rule_type: FILTER_CREATED_AFTER,
            value: dateAfter.toISOString().substring(0, 10),
          },
          {
            rule_type: FILTER_CREATED_BEFORE,
            value: dateBefore.toISOString().substring(0, 10),
          },
        ]
      }
      switch (type) {
        case DataType.Correspondent:
          return {
            rule_type: FILTER_CORRESPONDENT,
            value: (i as Correspondent).id.toString(),
          }
        case DataType.DocumentType:
          return {
            rule_type: FILTER_DOCUMENT_TYPE,
            value: (i as DocumentType).id.toString(),
          }
        case DataType.StoragePath:
          return {
            rule_type: FILTER_STORAGE_PATH,
            value: (i as StoragePath).id.toString(),
          }
        case DataType.Tag:
          return {
            rule_type: FILTER_HAS_TAGS_ALL,
            value: (i as Tag).id.toString(),
          }
      }
    })

    this.documentListViewService.quickFilter(filterRules)
  }

  private getCustomFields() {
    this.customFieldsService
      .listAll()
      .pipe(first(), takeUntil(this.unsubscribeNotifier))
      .subscribe((result) => (this.customFields = result.results))
  }

  public refreshCustomFields() {
    this.customFieldsService.clearCache()
    this.getCustomFields()
  }

  public getCustomFieldFromInstance(
    instance: CustomFieldInstance
  ): CustomField {
    return this.customFields?.find((f) => f.id === instance.field)
  }

  public getCustomFieldError(index: number) {
    const fieldError = this.error?.custom_fields?.[index]
    return fieldError?.['non_field_errors'] ?? fieldError?.['value']
  }

  private updateFormForCustomFields(emitEvent: boolean = false) {
    this.customFieldFormFields.clear({ emitEvent: false })
    this.document.custom_fields?.forEach((fieldInstance) => {
      this.customFieldFormFields.push(
        new FormGroup({
          field: new FormControl(
            this.getCustomFieldFromInstance(fieldInstance)?.id
          ),
          value: new FormControl(fieldInstance.value),
        }),
        { emitEvent }
      )
    })
  }

  public addField(field: CustomField) {
    this.document.custom_fields.push({
      field: field.id,
      value: null,
      document: this.documentId,
      created: new Date(),
    })
    this.updateFormForCustomFields(true)
  }

  public removeField(fieldInstance: CustomFieldInstance) {
    this.document.custom_fields.splice(
      this.document.custom_fields.indexOf(fieldInstance),
      1
    )
    this.updateFormForCustomFields(true)
    this.documentForm.updateValueAndValidity()
  }

  splitDocument() {
    let modal = this.modalService.open(SplitConfirmDialogComponent, {
      backdrop: 'static',
      size: 'lg',
    })
    modal.componentInstance.title = $localize`Split confirm`
    modal.componentInstance.messageBold = $localize`This operation will split the selected document(s) into new documents.`
    modal.componentInstance.btnCaption = $localize`Proceed`
    modal.componentInstance.documentID = this.document.id
    modal.componentInstance.confirmClicked
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        modal.componentInstance.buttonsEnabled = false
        this.documentsService
          .bulkEdit([this.document.id], 'split', {
            pages: modal.componentInstance.pagesString,
            delete_originals: modal.componentInstance.deleteOriginal,
          })
          .pipe(first(), takeUntil(this.unsubscribeNotifier))
          .subscribe({
            next: () => {
              this.toastService.showInfo(
                $localize`Split operation will begin in the background.`
              )
              modal.close()
            },
            error: (error) => {
              if (modal) {
                modal.componentInstance.buttonsEnabled = true
              }
              this.toastService.showError(
                $localize`Error executing split operation`,
                error
              )
            },
          })
      })
  }

  rotateDocument() {
    let modal = this.modalService.open(RotateConfirmDialogComponent, {
      backdrop: 'static',
      size: 'lg',
    })
    modal.componentInstance.title = $localize`Rotate confirm`
    modal.componentInstance.messageBold = $localize`This operation will permanently rotate the original version of the current document.`
    modal.componentInstance.btnCaption = $localize`Proceed`
    modal.componentInstance.documentID = this.document.id
    modal.componentInstance.showPDFNote = false
    modal.componentInstance.confirmClicked
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        modal.componentInstance.buttonsEnabled = false
        this.documentsService
          .bulkEdit([this.document.id], 'rotate', {
            degrees: modal.componentInstance.degrees,
          })
          .pipe(first(), takeUntil(this.unsubscribeNotifier))
          .subscribe({
            next: () => {
              this.toastService.show({
                content: $localize`Rotation will begin in the background. Close and re-open the document after the operation has completed to see the changes.`,
                delay: 8000,
                action: this.close.bind(this),
                actionName: $localize`Close`,
              })
              modal.close()
            },
            error: (error) => {
              if (modal) {
                modal.componentInstance.buttonsEnabled = true
              }
              this.toastService.showError(
                $localize`Error executing rotate operation`,
                error
              )
            },
          })
      })
  }

  deletePages() {
    let modal = this.modalService.open(DeletePagesConfirmDialogComponent, {
      backdrop: 'static',
    })
    modal.componentInstance.title = $localize`Delete pages confirm`
    modal.componentInstance.messageBold = $localize`This operation will permanently delete the selected pages from the original document.`
    modal.componentInstance.btnCaption = $localize`Proceed`
    modal.componentInstance.documentID = this.document.id
    modal.componentInstance.confirmClicked
      .pipe(takeUntil(this.unsubscribeNotifier))
      .subscribe(() => {
        modal.componentInstance.buttonsEnabled = false
        this.documentsService
          .bulkEdit([this.document.id], 'delete_pages', {
            pages: modal.componentInstance.pages,
          })
          .pipe(first(), takeUntil(this.unsubscribeNotifier))
          .subscribe({
            next: () => {
              this.toastService.showInfo(
                $localize`Delete pages operation will begin in the background. Close and re-open or reload this document after the operation has completed to see the changes.`
              )
              modal.close()
            },
            error: (error) => {
              if (modal) {
                modal.componentInstance.buttonsEnabled = true
              }
              this.toastService.showError(
                $localize`Error executing delete pages operation`,
                error
              )
            },
          })
      })
  }

  private tryRenderTiff() {
    this.http.get(this.previewUrl, { responseType: 'arraybuffer' }).subscribe({
      next: (res) => {
        /* istanbul ignore next */
        try {
          // See UTIF.js > _imgLoaded
          const tiffIfds: any[] = UTIF.decode(res)
          var vsns = tiffIfds,
            ma = 0,
            page = vsns[0]
          if (tiffIfds[0].subIFD) vsns = vsns.concat(tiffIfds[0].subIFD)
          for (var i = 0; i < vsns.length; i++) {
            var img = vsns[i]
            if (img['t258'] == null || img['t258'].length < 3) continue
            var ar = img['t256'] * img['t257']
            if (ar > ma) {
              ma = ar
              page = img
            }
          }
          UTIF.decodeImage(res, page, tiffIfds)
          const rgba = UTIF.toRGBA8(page)
          const { width: w, height: h } = page
          var cnv = document.createElement('canvas')
          cnv.width = w
          cnv.height = h
          var ctx = cnv.getContext('2d'),
            imgd = ctx.createImageData(w, h)
          for (var i = 0; i < rgba.length; i++) imgd.data[i] = rgba[i]
          ctx.putImageData(imgd, 0, 0)
          this.tiffURL = cnv.toDataURL()
        } catch (err) {
          this.tiffError = $localize`An error occurred loading tiff: ${err.toString()}`
        }
      },
      error: (err) => {
        this.tiffError = $localize`An error occurred loading tiff: ${err.toString()}`
      },
    })
  }
}
