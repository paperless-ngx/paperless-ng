import { DragDropModule } from '@angular/cdk/drag-drop'
import { DatePipe, ViewportScroller } from '@angular/common'
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http'
import { provideHttpClientTesting } from '@angular/common/http/testing'
import { ComponentFixture, TestBed } from '@angular/core/testing'
import { FormsModule, ReactiveFormsModule } from '@angular/forms'
import { By } from '@angular/platform-browser'
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router'
import { RouterTestingModule } from '@angular/router/testing'
import {
  NgbAlertModule,
  NgbModal,
  NgbModalModule,
  NgbModule,
  NgbNavLink,
} from '@ng-bootstrap/ng-bootstrap'
import { NgSelectModule } from '@ng-select/ng-select'
import { NgxBootstrapIconsModule, allIcons } from 'ngx-bootstrap-icons'
import { of, throwError } from 'rxjs'
import { routes } from 'src/app/app-routing.module'
import {
  InstallType,
  SystemStatus,
  SystemStatusItemStatus,
} from 'src/app/data/system-status'
import { SETTINGS_KEYS } from 'src/app/data/ui-settings'
import { IfOwnerDirective } from 'src/app/directives/if-owner.directive'
import { IfPermissionsDirective } from 'src/app/directives/if-permissions.directive'
import { PermissionsGuard } from 'src/app/guards/permissions.guard'
import { CustomDatePipe } from 'src/app/pipes/custom-date.pipe'
import { SafeHtmlPipe } from 'src/app/pipes/safehtml.pipe'
import { PermissionsService } from 'src/app/services/permissions.service'
import { GroupService } from 'src/app/services/rest/group.service'
import { UserService } from 'src/app/services/rest/user.service'
import { SettingsService } from 'src/app/services/settings.service'
import { SystemStatusService } from 'src/app/services/system-status.service'
import { Toast, ToastService } from 'src/app/services/toast.service'
import { ConfirmButtonComponent } from '../../common/confirm-button/confirm-button.component'
import { ConfirmDialogComponent } from '../../common/confirm-dialog/confirm-dialog.component'
import { CheckComponent } from '../../common/input/check/check.component'
import { ColorComponent } from '../../common/input/color/color.component'
import { DragDropSelectComponent } from '../../common/input/drag-drop-select/drag-drop-select.component'
import { NumberComponent } from '../../common/input/number/number.component'
import { PermissionsGroupComponent } from '../../common/input/permissions/permissions-group/permissions-group.component'
import { PermissionsUserComponent } from '../../common/input/permissions/permissions-user/permissions-user.component'
import { SelectComponent } from '../../common/input/select/select.component'
import { TagsComponent } from '../../common/input/tags/tags.component'
import { TextComponent } from '../../common/input/text/text.component'
import { PageHeaderComponent } from '../../common/page-header/page-header.component'
import { SystemStatusDialogComponent } from '../../common/system-status-dialog/system-status-dialog.component'
import { SettingsComponent } from './settings.component'

const users = [
  { id: 1, username: 'user1', is_superuser: false },
  { id: 2, username: 'user2', is_superuser: false },
]
const groups = [
  { id: 1, name: 'group1' },
  { id: 2, name: 'group2' },
]

describe('SettingsComponent', () => {
  let component: SettingsComponent
  let fixture: ComponentFixture<SettingsComponent>
  let router: Router
  let settingsService: SettingsService
  let activatedRoute: ActivatedRoute
  let viewportScroller: ViewportScroller
  let toastService: ToastService
  let userService: UserService
  let permissionsService: PermissionsService
  let groupService: GroupService
  let modalService: NgbModal
  let systemStatusService: SystemStatusService

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [
        NgbModule,
        RouterTestingModule.withRoutes(routes),
        FormsModule,
        ReactiveFormsModule,
        NgbAlertModule,
        NgSelectModule,
        NgxBootstrapIconsModule.pick(allIcons),
        NgbModalModule,
        DragDropModule,
        SettingsComponent,
        PageHeaderComponent,
        IfPermissionsDirective,
        CustomDatePipe,
        ConfirmDialogComponent,
        CheckComponent,
        ColorComponent,
        SafeHtmlPipe,
        SelectComponent,
        TextComponent,
        NumberComponent,
        TagsComponent,
        PermissionsUserComponent,
        PermissionsGroupComponent,
        IfOwnerDirective,
        ConfirmButtonComponent,
        DragDropSelectComponent,
      ],
      providers: [
        CustomDatePipe,
        DatePipe,
        PermissionsGuard,
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    }).compileComponents()

    router = TestBed.inject(Router)
    activatedRoute = TestBed.inject(ActivatedRoute)
    viewportScroller = TestBed.inject(ViewportScroller)
    toastService = TestBed.inject(ToastService)
    settingsService = TestBed.inject(SettingsService)
    settingsService.currentUser = users[0]
    userService = TestBed.inject(UserService)
    permissionsService = TestBed.inject(PermissionsService)
    modalService = TestBed.inject(NgbModal)
    systemStatusService = TestBed.inject(SystemStatusService)
    jest.spyOn(permissionsService, 'currentUserCan').mockReturnValue(true)
    jest
      .spyOn(permissionsService, 'currentUserHasObjectPermissions')
      .mockReturnValue(true)
    jest
      .spyOn(permissionsService, 'currentUserOwnsObject')
      .mockReturnValue(true)
    groupService = TestBed.inject(GroupService)
  })

  function completeSetup(excludeService = null) {
    if (excludeService !== userService) {
      jest.spyOn(userService, 'listAll').mockReturnValue(
        of({
          all: users.map((u) => u.id),
          count: users.length,
          results: users.concat([]),
        })
      )
    }
    if (excludeService !== groupService) {
      jest.spyOn(groupService, 'listAll').mockReturnValue(
        of({
          all: groups.map((g) => g.id),
          count: groups.length,
          results: groups.concat([]),
        })
      )
    }

    fixture = TestBed.createComponent(SettingsComponent)
    component = fixture.componentInstance
    fixture.detectChanges()
  }

  it('should support tabbed settings & change URL, prevent navigation if dirty confirmation rejected', () => {
    completeSetup()
    const navigateSpy = jest.spyOn(router, 'navigate')
    const tabButtons = fixture.debugElement.queryAll(By.directive(NgbNavLink))
    tabButtons[1].nativeElement.dispatchEvent(new MouseEvent('click'))
    expect(navigateSpy).toHaveBeenCalledWith(['settings', 'permissions'])
    tabButtons[2].nativeElement.dispatchEvent(new MouseEvent('click'))
    expect(navigateSpy).toHaveBeenCalledWith(['settings', 'notifications'])

    const initSpy = jest.spyOn(component, 'initialize')
    component.isDirty = true // mock dirty
    navigateSpy.mockResolvedValueOnce(false) // nav rejected cause dirty
    tabButtons[0].nativeElement.dispatchEvent(new MouseEvent('click'))
    expect(navigateSpy).toHaveBeenCalledWith(['settings', 'general'])
    expect(initSpy).not.toHaveBeenCalled()

    navigateSpy.mockResolvedValueOnce(true) // nav accepted even though dirty
    tabButtons[1].nativeElement.dispatchEvent(new MouseEvent('click'))
    expect(navigateSpy).toHaveBeenCalledWith(['settings', 'notifications'])
    expect(initSpy).toHaveBeenCalled()
  })

  it('should support direct link to tab by URL, scroll if needed', () => {
    completeSetup()
    jest
      .spyOn(activatedRoute, 'paramMap', 'get')
      .mockReturnValue(of(convertToParamMap({ section: 'notifications' })))
    activatedRoute.snapshot.fragment = '#notifications'
    const scrollSpy = jest.spyOn(viewportScroller, 'scrollToAnchor')
    component.ngOnInit()
    expect(component.activeNavID).toEqual(3) // Notifications
    component.ngAfterViewInit()
    expect(scrollSpy).toHaveBeenCalledWith('#notifications')
  })

  it('should support save local settings updating appearance settings and calling API, show error', () => {
    completeSetup()
    const toastErrorSpy = jest.spyOn(toastService, 'showError')
    const toastSpy = jest.spyOn(toastService, 'show')
    const storeSpy = jest.spyOn(settingsService, 'storeSettings')
    const appearanceSettingsSpy = jest.spyOn(
      settingsService,
      'updateAppearanceSettings'
    )
    const setSpy = jest.spyOn(settingsService, 'set')

    // error first
    storeSpy.mockReturnValueOnce(
      throwError(() => new Error('unable to save settings'))
    )
    component.saveSettings()

    expect(toastErrorSpy).toHaveBeenCalled()
    expect(storeSpy).toHaveBeenCalled()
    expect(appearanceSettingsSpy).not.toHaveBeenCalled()
    expect(setSpy).toHaveBeenCalledTimes(29)

    // succeed
    storeSpy.mockReturnValueOnce(of(true))
    component.saveSettings()
    expect(toastSpy).toHaveBeenCalled()
    expect(appearanceSettingsSpy).toHaveBeenCalled()
  })

  it('should offer reload if settings changes require', () => {
    completeSetup()
    let toast: Toast
    toastService.getToasts().subscribe((t) => (toast = t[0]))
    component.initialize(true) // reset
    component.store.getValue()['displayLanguage'] = 'en-US'
    component.store.getValue()['updateCheckingEnabled'] = false
    component.settingsForm.value.displayLanguage = 'en-GB'
    jest.spyOn(settingsService, 'storeSettings').mockReturnValue(of(true))
    component.saveSettings()
    expect(toast.actionName).toEqual('Reload now')

    component.settingsForm.value.updateCheckingEnabled = true
    component.saveSettings()

    expect(toast.actionName).toEqual('Reload now')
    toast.action()
  })

  it('should allow setting theme color, visually apply change immediately but not save', () => {
    completeSetup()
    const appearanceSpy = jest.spyOn(
      settingsService,
      'updateAppearanceSettings'
    )
    const colorInput = fixture.debugElement.query(By.directive(ColorComponent))
    colorInput.query(By.css('input')).nativeElement.value = '#ff0000'
    colorInput
      .query(By.css('input'))
      .nativeElement.dispatchEvent(new Event('change'))
    fixture.detectChanges()
    expect(appearanceSpy).toHaveBeenCalled()
    expect(settingsService.get(SETTINGS_KEYS.THEME_COLOR)).toEqual('')
    component.clearThemeColor()
  })

  it('should show errors on load if load users failure', () => {
    const toastErrorSpy = jest.spyOn(toastService, 'showError')
    jest
      .spyOn(userService, 'listAll')
      .mockImplementation(() =>
        throwError(() => new Error('failed to load users'))
      )
    completeSetup(userService)
    fixture.detectChanges()
    expect(toastErrorSpy).toBeCalled()
  })

  it('should show errors on load if load groups failure', () => {
    const toastErrorSpy = jest.spyOn(toastService, 'showError')
    jest
      .spyOn(groupService, 'listAll')
      .mockImplementation(() =>
        throwError(() => new Error('failed to load groups'))
      )
    completeSetup(groupService)
    fixture.detectChanges()
    expect(toastErrorSpy).toBeCalled()
  })

  it('should load system status on initialize, show errors if needed', () => {
    const status: SystemStatus = {
      pngx_version: '2.4.3',
      server_os: 'macOS-14.1.1-arm64-arm-64bit',
      install_type: InstallType.BareMetal,
      storage: { total: 494384795648, available: 13573525504 },
      database: {
        type: 'sqlite',
        url: '/paperless-ngx/data/db.sqlite3',
        status: SystemStatusItemStatus.ERROR,
        error: null,
        migration_status: {
          latest_migration: 'socialaccount.0006_alter_socialaccount_extra_data',
          unapplied_migrations: [],
        },
      },
      tasks: {
        redis_url: 'redis://localhost:6379',
        redis_status: SystemStatusItemStatus.ERROR,
        redis_error:
          'Error 61 connecting to localhost:6379. Connection refused.',
        celery_status: SystemStatusItemStatus.ERROR,
        celery_url: 'celery@localhost',
        celery_error: 'Error connecting to celery@localhost',
        index_status: SystemStatusItemStatus.OK,
        index_last_modified: new Date().toISOString(),
        index_error: null,
        classifier_status: SystemStatusItemStatus.OK,
        classifier_last_trained: new Date().toISOString(),
        classifier_error: null,
        sanity_check_status: SystemStatusItemStatus.ERROR,
        sanity_check_last_run: new Date().toISOString(),
        sanity_check_error: 'Error running sanity check.',
      },
    }
    jest.spyOn(systemStatusService, 'get').mockReturnValue(of(status))
    jest.spyOn(permissionsService, 'isAdmin').mockReturnValue(true)
    completeSetup()
    expect(component['systemStatus']).toEqual(status) // private
    expect(component.systemStatusHasErrors).toBeTruthy()
    // coverage
    component['systemStatus'].database.status = SystemStatusItemStatus.OK
    component['systemStatus'].tasks.redis_status = SystemStatusItemStatus.OK
    component['systemStatus'].tasks.celery_status = SystemStatusItemStatus.OK
    expect(component.systemStatusHasErrors).toBeFalsy()
  })

  it('should open system status dialog', () => {
    const modalOpenSpy = jest.spyOn(modalService, 'open')
    completeSetup()
    component.showSystemStatus()
    expect(modalOpenSpy).toHaveBeenCalledWith(SystemStatusDialogComponent, {
      size: 'xl',
    })
  })

  it('should support reset', () => {
    completeSetup()
    component.settingsForm.get('themeColor').setValue('#ff0000')
    component.reset()
    expect(component.settingsForm.get('themeColor').value).toEqual('')
  })
})
