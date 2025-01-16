import { ComponentFixture, TestBed } from '@angular/core/testing'

import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http'
import { provideHttpClientTesting } from '@angular/common/http/testing'
import { NgxBootstrapIconsModule, allIcons } from 'ngx-bootstrap-icons'
import { of, throwError } from 'rxjs'
import { IfPermissionsDirective } from 'src/app/directives/if-permissions.directive'
import { PermissionsService } from 'src/app/services/permissions.service'
import { DocumentService } from 'src/app/services/rest/document.service'
import { ToastService } from 'src/app/services/toast.service'
import { EmailDocumentDropdownComponent } from './email-document-dropdown.component'

describe('EmailDocumentDropdownComponent', () => {
  let component: EmailDocumentDropdownComponent
  let fixture: ComponentFixture<EmailDocumentDropdownComponent>
  let documentService: DocumentService
  let permissionsService: PermissionsService
  let toastService: ToastService

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        EmailDocumentDropdownComponent,
        IfPermissionsDirective,
        NgxBootstrapIconsModule.pick(allIcons),
      ],
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    }).compileComponents()

    fixture = TestBed.createComponent(EmailDocumentDropdownComponent)
    documentService = TestBed.inject(DocumentService)
    toastService = TestBed.inject(ToastService)
    component = fixture.componentInstance
    fixture.detectChanges()
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
