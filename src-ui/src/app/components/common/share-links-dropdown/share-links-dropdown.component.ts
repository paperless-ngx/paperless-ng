import { Clipboard } from '@angular/cdk/clipboard'
import { Component, Input, OnInit } from '@angular/core'
import { FormsModule, ReactiveFormsModule } from '@angular/forms'
import { NgbDropdownModule } from '@ng-bootstrap/ng-bootstrap'
import { NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import { first } from 'rxjs'
import { FileVersion, ShareLink } from 'src/app/data/share-link'
import { ShareLinkService } from 'src/app/services/rest/share-link.service'
import { ToastService } from 'src/app/services/toast.service'
import { environment } from 'src/environments/environment'

@Component({
  selector: 'pngx-share-links-dropdown',
  templateUrl: './share-links-dropdown.component.html',
  styleUrls: ['./share-links-dropdown.component.scss'],
  imports: [
    FormsModule,
    ReactiveFormsModule,
    NgbDropdownModule,
    NgxBootstrapIconsModule,
  ],
})
export class ShareLinksDropdownComponent implements OnInit {
  EXPIRATION_OPTIONS = [
    { label: $localize`1 day`, value: 1 },
    { label: $localize`7 days`, value: 7 },
    { label: $localize`30 days`, value: 30 },
    { label: $localize`Never`, value: null },
  ]

  @Input()
  title = $localize`Share Links`

  _documentId: number

  @Input()
  set documentId(id: number) {
    if (id !== undefined) {
      this._documentId = id
      this.refresh()
    }
  }

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

  shareLinks: ShareLink[]

  loading: boolean = false

  copied: number

  expirationDays: number = 7

  useArchiveVersion: boolean = true

  constructor(
    private shareLinkService: ShareLinkService,
    private toastService: ToastService,
    private clipboard: Clipboard
  ) {}

  ngOnInit(): void {
    if (this._documentId !== undefined) this.refresh()
  }

  refresh() {
    if (this._documentId === undefined) return
    this.loading = true
    this.shareLinkService
      .getLinksForDocument(this._documentId)
      .pipe(first())
      .subscribe({
        next: (results) => {
          this.loading = false
          this.shareLinks = results
        },
        error: (e) => {
          this.toastService.showError(
            $localize`Error retrieving links`,
            10000,
            e
          )
        },
      })
  }

  getShareUrl(link: ShareLink): string {
    const apiURL = new URL(environment.apiBaseUrl)
    return `${apiURL.origin}${apiURL.pathname.replace(/\/api\/$/, '/share/')}${
      link.slug
    }`
  }

  getDaysRemaining(link: ShareLink): string {
    const days: number = Math.round(
      (Date.parse(link.expiration) - Date.now()) / (1000 * 60 * 60 * 24)
    )
    return days === 1 ? $localize`1 day` : $localize`${days} days`
  }

  copy(link: ShareLink) {
    const success = this.clipboard.copy(this.getShareUrl(link))
    if (success) {
      this.copied = link.id
      setTimeout(() => {
        this.copied = null
      }, 3000)
    }
  }

  canShare(link: ShareLink): boolean {
    return (
      navigator?.canShare && navigator.canShare({ url: this.getShareUrl(link) })
    )
  }

  share(link: ShareLink) {
    navigator.share({ url: this.getShareUrl(link) })
  }

  delete(link: ShareLink) {
    this.shareLinkService.delete(link).subscribe({
      next: () => {
        this.refresh()
      },
      error: (e) => {
        this.toastService.showError($localize`Error deleting link`, 10000, e)
      },
    })
  }

  createLink() {
    let expiration
    if (this.expirationDays) {
      expiration = new Date()
      expiration.setDate(expiration.getDate() + this.expirationDays)
    }
    this.loading = true
    this.shareLinkService
      .createLinkForDocument(
        this._documentId,
        this.useArchiveVersion ? FileVersion.Archive : FileVersion.Original,
        expiration
      )
      .subscribe({
        next: (result) => {
          this.loading = false
          setTimeout(() => {
            this.copy(result)
          }, 10)
          this.refresh()
        },
        error: (e) => {
          this.loading = false
          this.toastService.showError($localize`Error creating link`, 10000, e)
        },
      })
  }
}
