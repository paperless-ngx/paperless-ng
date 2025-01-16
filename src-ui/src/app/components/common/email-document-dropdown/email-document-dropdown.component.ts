import { Component, Input } from '@angular/core'
import { FormsModule } from '@angular/forms'
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap'
import { NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import { SETTINGS_KEYS } from 'src/app/data/ui-settings'
import { DocumentService } from 'src/app/services/rest/document.service'
import { SettingsService } from 'src/app/services/settings.service'
import { ToastService } from 'src/app/services/toast.service'
import { LoadingComponentWithPermissions } from '../../loading-component/loading.component'

@Component({
  selector: 'pngx-email-document-dropdown',
  imports: [FormsModule, NgbDropdownModule, NgxBootstrapIconsModule],
  templateUrl: './email-document-dropdown.component.html',
  styleUrl: './email-document-dropdown.component.scss',
})
export class EmailDocumentDropdownComponent extends LoadingComponentWithPermissions {
  @Input()
  title = $localize`Email Document`

  @Input()
  documentId: number

  @Input()
  disabled: boolean = false

  private _hasArchiveVersion: boolean = true

  @Input()
  set hasArchiveVersion(value: boolean) {
    this._hasArchiveVersion = value
    this.useArchiveVersion = value
  }

  get hasArchiveVersion(): boolean {
    return this._hasArchiveVersion
  }

  public useArchiveVersion: boolean = true

  public emailAddress: string = ''
  public emailSubject: string = ''
  public emailMessage: string = ''

  get emailEnabled(): boolean {
    return this.settingsService.get(SETTINGS_KEYS.EMAIL_ENABLED)
  }

  constructor(
    private documentService: DocumentService,
    private toastService: ToastService,
    private settingsService: SettingsService
  ) {
    super()
    this.loading = false
  }

  public emailDocument() {
    this.loading = true
    this.documentService
      .emailDocument(
        this.documentId,
        this.emailAddress,
        this.emailSubject,
        this.emailMessage,
        this.useArchiveVersion
      )
      .subscribe({
        next: () => {
          this.loading = false
          this.emailAddress = ''
          this.emailSubject = ''
          this.emailMessage = ''
          this.toastService.showInfo($localize`Email sent`)
        },
        error: (e) => {
          this.loading = false
          this.toastService.showError($localize`Error emailing document`, e)
        },
      })
  }
}
