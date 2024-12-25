import { Clipboard } from '@angular/cdk/clipboard'
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http'
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing'
import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing'
import { By } from '@angular/platform-browser'
import { NgxBootstrapIconsModule, allIcons } from 'ngx-bootstrap-icons'
import { of, throwError } from 'rxjs'
import { FileVersion, ShareLink } from 'src/app/data/share-link'
import { IfPermissionsDirective } from 'src/app/directives/if-permissions.directive'
import { PermissionsService } from 'src/app/services/permissions.service'
import { DocumentService } from 'src/app/services/rest/document.service'
import { ShareLinkService } from 'src/app/services/rest/share-link.service'
import { ToastService } from 'src/app/services/toast.service'
import { environment } from 'src/environments/environment'
import { ShareDocumentDropdownComponent } from './share-document-dropdown.component'

describe('ShareDocumentDropdownComponent', () => {
  let component: ShareDocumentDropdownComponent
  let fixture: ComponentFixture<ShareDocumentDropdownComponent>
  let shareLinkService: ShareLinkService
  let documentService: DocumentService
  let permissionsService: PermissionsService
  let toastService: ToastService
  let httpController: HttpTestingController
  let clipboard: Clipboard

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [],
      imports: [
        ShareDocumentDropdownComponent,
        IfPermissionsDirective,
        NgxBootstrapIconsModule.pick(allIcons),
      ],
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    })

    fixture = TestBed.createComponent(ShareDocumentDropdownComponent)
    shareLinkService = TestBed.inject(ShareLinkService)
    documentService = TestBed.inject(DocumentService)
    permissionsService = TestBed.inject(PermissionsService)
    toastService = TestBed.inject(ToastService)
    httpController = TestBed.inject(HttpTestingController)
    clipboard = TestBed.inject(Clipboard)

    jest.spyOn(permissionsService, 'currentUserCan').mockReturnValue(true)
    component = fixture.componentInstance
    fixture.detectChanges()
  })

  it('should support refresh to retrieve links', () => {
    const getSpy = jest.spyOn(shareLinkService, 'getLinksForDocument')
    component.documentId = 99

    const now = new Date()
    const expiration7days = new Date()
    expiration7days.setDate(now.getDate() + 7)

    getSpy.mockReturnValue(
      of([
        {
          id: 1,
          slug: '1234slug',
          created: now.toISOString(),
          document: 99,
          file_version: FileVersion.Archive,
          expiration: expiration7days.toISOString(),
        },
        {
          id: 1,
          slug: '1234slug',
          created: now.toISOString(),
          document: 99,
          file_version: FileVersion.Original,
          expiration: null,
        },
      ])
    )

    component.refresh()
    expect(getSpy).toHaveBeenCalled()

    fixture.detectChanges()

    expect(component.shareLinks).toHaveLength(2)
  })

  it('should show error on refresh if needed', () => {
    const toastSpy = jest.spyOn(toastService, 'showError')
    jest
      .spyOn(shareLinkService, 'getLinksForDocument')
      .mockReturnValueOnce(throwError(() => new Error('Unable to get links')))
    component.documentId = 99

    component.ngOnInit()
    fixture.detectChanges()
    expect(toastSpy).toHaveBeenCalled()
  })

  it('should support link creation then refresh & copy url', fakeAsync(() => {
    const createSpy = jest.spyOn(shareLinkService, 'createLinkForDocument')
    component.documentId = 99
    component.expirationDays = 7
    component.useArchiveVersion = false

    const expiration = new Date()
    expiration.setDate(expiration.getDate() + 7)

    const copySpy = jest.spyOn(clipboard, 'copy')
    copySpy.mockReturnValue(true)
    const refreshSpy = jest.spyOn(component, 'refresh')

    component.createLink()
    expect(createSpy).toHaveBeenCalledWith(99, 'original', expiration)

    httpController.expectOne(`${environment.apiBaseUrl}share_links/`).flush({
      id: 1,
      slug: '1234slug',
      document: 99,
      expiration: expiration.toISOString(),
    })
    fixture.detectChanges()
    tick(3000)

    expect(refreshSpy).toHaveBeenCalled()
    expect(copySpy).toHaveBeenCalled()
    expect(component.copied).toEqual(1)
    tick(100) // copy timeout
  }))

  it('should show error on link creation if needed', () => {
    component.documentId = 99
    component.expirationDays = 7

    const expiration = new Date()
    expiration.setDate(expiration.getDate() + 7)

    const toastSpy = jest.spyOn(toastService, 'showError')

    component.createLink()

    httpController
      .expectOne(`${environment.apiBaseUrl}share_links/`)
      .flush(
        { error: 'Share link error' },
        { status: 500, statusText: 'error' }
      )
    fixture.detectChanges()

    expect(toastSpy).toHaveBeenCalled()
  })

  it('should support delete links & refresh', () => {
    const deleteSpy = jest.spyOn(shareLinkService, 'delete')
    deleteSpy.mockReturnValue(of(true))
    const refreshSpy = jest.spyOn(component, 'refresh')

    component.delete({ id: 12 } as ShareLink)
    fixture.detectChanges()
    expect(deleteSpy).toHaveBeenCalledWith({ id: 12 })
    expect(refreshSpy).toHaveBeenCalled()
  })

  it('should show error on delete if needed', () => {
    const toastSpy = jest.spyOn(toastService, 'showError')
    jest
      .spyOn(shareLinkService, 'delete')
      .mockReturnValueOnce(throwError(() => new Error('Unable to delete link')))
    component.delete(null)
    fixture.detectChanges()
    expect(toastSpy).toHaveBeenCalled()
  })

  it('should format days remaining', () => {
    const now = new Date()
    const expiration7days = new Date()
    expiration7days.setDate(now.getDate() + 7)
    const expiration1day = new Date()
    expiration1day.setDate(now.getDate() + 1)

    expect(
      component.getDaysRemaining({
        expiration: expiration7days.toISOString(),
      } as ShareLink)
    ).toEqual('7 days')
    expect(
      component.getDaysRemaining({
        expiration: expiration1day.toISOString(),
      } as ShareLink)
    ).toEqual('1 day')
  })

  // coverage
  it('should support share', () => {
    const link = { slug: '12345slug' } as ShareLink
    if (!('share' in navigator))
      Object.defineProperty(navigator, 'share', { value: (obj: any) => {} })
    // const navigatorSpy = jest.spyOn(navigator, 'share')
    component.share(link)
    // expect(navigatorSpy).toHaveBeenCalledWith({ url: component.getShareUrl(link) })
  })

  it('should correctly generate share URLs', () => {
    environment.apiBaseUrl = 'http://example.com/api/'
    expect(component.getShareUrl({ slug: '123abc123' } as any)).toEqual(
      'http://example.com/share/123abc123'
    )
    environment.apiBaseUrl = 'http://example.domainwithapiinit.com/api/'
    expect(component.getShareUrl({ slug: '123abc123' } as any)).toEqual(
      'http://example.domainwithapiinit.com/share/123abc123'
    )
    environment.apiBaseUrl = 'http://example.domainwithapiinit.com:1234/api/'
    expect(component.getShareUrl({ slug: '123abc123' } as any)).toEqual(
      'http://example.domainwithapiinit.com:1234/share/123abc123'
    )
    environment.apiBaseUrl =
      'http://example.domainwithapiinit.com:1234/subpath/api/'
    expect(component.getShareUrl({ slug: '123abc123' } as any)).toEqual(
      'http://example.domainwithapiinit.com:1234/subpath/share/123abc123'
    )
  })

  it('should disable archive switch & option if no archive available', () => {
    component.hasArchiveVersion = false
    component.ngOnInit()
    fixture.detectChanges()
    expect(component.useArchiveVersion).toBeFalsy()
    expect(
      fixture.debugElement.query(By.css("input[type='checkbox']")).attributes[
        'ng-reflect-is-disabled'
      ]
    ).toBeTruthy()
  })

  it('should support sending document via email, showing error if needed', () => {
    const toastErrorSpy = jest.spyOn(toastService, 'showError')
    const toastSuccessSpy = jest.spyOn(toastService, 'showInfo')
    component.emailAddress = 'hello@paperless-ngx.com'
    component.emailSubject = 'Hello'
    component.emailMessage = 'World'
    jest
      .spyOn(documentService, 'emailDocument')
      .mockReturnValue(throwError(() => new Error('Unable to email document')))
    component.emailDocument()
    expect(toastErrorSpy).toHaveBeenCalled()

    jest.spyOn(documentService, 'emailDocument').mockReturnValue(of(true))
    component.emailDocument()
    expect(toastSuccessSpy).toHaveBeenCalled()
  })
})
