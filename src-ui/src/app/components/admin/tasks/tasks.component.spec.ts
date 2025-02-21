import { DatePipe } from '@angular/common'
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http'
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing'
import { ComponentFixture, TestBed } from '@angular/core/testing'
import { FormsModule } from '@angular/forms'
import { By } from '@angular/platform-browser'
import { Router } from '@angular/router'
import { RouterTestingModule } from '@angular/router/testing'
import {
  NgbModal,
  NgbModalRef,
  NgbModule,
  NgbNavItem,
} from '@ng-bootstrap/ng-bootstrap'
import { allIcons, NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import { routes } from 'src/app/app-routing.module'
import {
  PaperlessTask,
  PaperlessTaskName,
  PaperlessTaskStatus,
  PaperlessTaskType,
} from 'src/app/data/paperless-task'
import { IfPermissionsDirective } from 'src/app/directives/if-permissions.directive'
import { PermissionsGuard } from 'src/app/guards/permissions.guard'
import { CustomDatePipe } from 'src/app/pipes/custom-date.pipe'
import { PermissionsService } from 'src/app/services/permissions.service'
import { TasksService } from 'src/app/services/tasks.service'
import { environment } from 'src/environments/environment'
import { ConfirmDialogComponent } from '../../common/confirm-dialog/confirm-dialog.component'
import { PageHeaderComponent } from '../../common/page-header/page-header.component'
import { TasksComponent, TaskTab } from './tasks.component'

const tasks: PaperlessTask[] = [
  {
    id: 467,
    task_id: '11ca1a5b-9f81-442c-b2c8-7e4ae53657f1',
    task_file_name: 'test.pdf',
    date_created: new Date('2023-03-01T10:26:03.093116Z'),
    date_done: new Date('2023-03-01T10:26:07.223048Z'),
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Failed,
    result: 'test.pd: Not consuming test.pdf: It is a duplicate of test (#100)',
    acknowledged: false,
    related_document: null,
  },
  {
    id: 466,
    task_id: '10ca1a5b-3c08-442c-b2c8-7e4ae53657f1',
    task_file_name: '191092.pdf',
    date_created: new Date('2023-03-01T09:26:03.093116Z'),
    date_done: new Date('2023-03-01T09:26:07.223048Z'),
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Failed,
    result:
      '191092.pd: Not consuming 191092.pdf: It is a duplicate of 191092 (#311)',
    acknowledged: false,
    related_document: null,
  },
  {
    id: 465,
    task_id: '3612d477-bb04-44e3-985b-ac580dd496d8',
    task_file_name: 'Scan Jun 6, 2023 at 3.19 PM.pdf',
    date_created: new Date('2023-06-06T15:22:05.722323-07:00'),
    date_done: new Date('2023-06-06T15:22:14.564305-07:00'),
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Pending,
    result: null,
    acknowledged: false,
    related_document: null,
  },
  {
    id: 464,
    task_id: '2eac4716-2aa6-4dcd-9953-264e11656d7e',
    task_file_name: 'paperless-mail-l4dkg8ir',
    date_created: new Date('2023-06-04T11:24:32.898089-07:00'),
    date_done: new Date('2023-06-04T11:24:44.678605-07:00'),
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Complete,
    result: 'Success. New document id 422 created',
    acknowledged: false,
    related_document: 422,
  },
  {
    id: 463,
    task_id: '28125528-1575-4d6b-99e6-168906e8fa5c',
    task_file_name: 'onlinePaymentSummary.pdf',
    date_created: new Date('2023-06-01T13:49:51.631305-07:00'),
    date_done: new Date('2023-06-01T13:49:54.190220-07:00'),
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Complete,
    result: 'Success. New document id 421 created',
    acknowledged: false,
    related_document: 421,
  },
  {
    id: 462,
    task_id: 'a5b9ca47-0c8e-490f-a04c-6db5d5fc09e5',
    task_file_name: 'paperless-mail-_rrpmqk6',
    date_created: new Date('2023-06-07T02:54:35.694916Z'),
    date_done: null,
    type: PaperlessTaskType.Auto,
    task_name: PaperlessTaskName.ConsumeFile,
    status: PaperlessTaskStatus.Started,
    result: null,
    acknowledged: false,
    related_document: null,
  },
]

describe('TasksComponent', () => {
  let component: TasksComponent
  let fixture: ComponentFixture<TasksComponent>
  let tasksService: TasksService
  let modalService: NgbModal
  let router: Router
  let httpTestingController: HttpTestingController
  let reloadSpy

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [
        NgbModule,
        RouterTestingModule.withRoutes(routes),
        NgxBootstrapIconsModule.pick(allIcons),
        FormsModule,
        TasksComponent,
        PageHeaderComponent,
        IfPermissionsDirective,
        CustomDatePipe,
        ConfirmDialogComponent,
      ],
      providers: [
        {
          provide: PermissionsService,
          useValue: {
            currentUserCan: () => true,
          },
        },
        CustomDatePipe,
        DatePipe,
        PermissionsGuard,
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    }).compileComponents()

    tasksService = TestBed.inject(TasksService)
    reloadSpy = jest.spyOn(tasksService, 'reload')
    httpTestingController = TestBed.inject(HttpTestingController)
    modalService = TestBed.inject(NgbModal)
    router = TestBed.inject(Router)
    fixture = TestBed.createComponent(TasksComponent)
    component = fixture.componentInstance
    jest.useFakeTimers()
    fixture.detectChanges()
    httpTestingController
      .expectOne(
        `${environment.apiBaseUrl}tasks/?task_name=consume_file&acknowledged=false`
      )
      .flush(tasks)
  })

  it('should display file tasks in 4 tabs by status', () => {
    const tabButtons = fixture.debugElement.queryAll(By.directive(NgbNavItem))

    let currentTasksLength = tasks.filter(
      (t) => t.status === PaperlessTaskStatus.Failed
    ).length
    component.activeTab = TaskTab.Failed
    fixture.detectChanges()
    expect(tabButtons[0].nativeElement.textContent).toEqual(
      `Failed${currentTasksLength}`
    )
    expect(
      fixture.debugElement.queryAll(By.css('table input[type="checkbox"]'))
    ).toHaveLength(currentTasksLength + 1)

    currentTasksLength = tasks.filter(
      (t) => t.status === PaperlessTaskStatus.Complete
    ).length
    component.activeTab = TaskTab.Completed
    fixture.detectChanges()
    expect(tabButtons[1].nativeElement.textContent).toEqual(
      `Complete${currentTasksLength}`
    )

    currentTasksLength = tasks.filter(
      (t) => t.status === PaperlessTaskStatus.Started
    ).length
    component.activeTab = TaskTab.Started
    fixture.detectChanges()
    expect(tabButtons[2].nativeElement.textContent).toEqual(
      `Started${currentTasksLength}`
    )

    currentTasksLength = tasks.filter(
      (t) => t.status === PaperlessTaskStatus.Pending
    ).length
    component.activeTab = TaskTab.Queued
    fixture.detectChanges()
    expect(tabButtons[3].nativeElement.textContent).toEqual(
      `Queued${currentTasksLength}`
    )
  })

  it('should to go page 1 between tab switch', () => {
    component.page = 10
    component.duringTabChange()
    expect(component.page).toEqual(1)
  })

  it('should support expanding / collapsing one task at a time', () => {
    component.expandTask(tasks[0])
    expect(component.expandedTask).toEqual(tasks[0].id)
    component.expandTask(tasks[1])
    expect(component.expandedTask).toEqual(tasks[1].id)
    component.expandTask(tasks[1])
    expect(component.expandedTask).toBeUndefined()
  })

  it('should support dismiss single task', () => {
    const dismissSpy = jest.spyOn(tasksService, 'dismissTasks')
    component.dismissTask(tasks[0])
    expect(dismissSpy).toHaveBeenCalledWith(new Set([tasks[0].id]))
  })

  it('should support dismiss specific checked tasks', () => {
    component.toggleSelected(tasks[0])
    component.toggleSelected(tasks[1])
    component.toggleSelected(tasks[3])
    component.toggleSelected(tasks[3]) // uncheck, for coverage
    const selected = new Set([tasks[0].id, tasks[1].id])
    expect(component.selectedTasks).toEqual(selected)
    let modal: NgbModalRef
    modalService.activeInstances.subscribe((m) => (modal = m[m.length - 1]))
    const dismissSpy = jest.spyOn(tasksService, 'dismissTasks')
    fixture.detectChanges()
    component.dismissTasks()
    expect(modal).not.toBeUndefined()
    modal.componentInstance.confirmClicked.emit()
    expect(dismissSpy).toHaveBeenCalledWith(selected)
  })

  it('should support dismiss all tasks', () => {
    let modal: NgbModalRef
    modalService.activeInstances.subscribe((m) => (modal = m[m.length - 1]))
    const dismissSpy = jest.spyOn(tasksService, 'dismissTasks')
    component.dismissTasks()
    expect(modal).not.toBeUndefined()
    modal.componentInstance.confirmClicked.emit()
    expect(dismissSpy).toHaveBeenCalledWith(new Set(tasks.map((t) => t.id)))
  })

  it('should support toggle all tasks', () => {
    const toggleCheck = fixture.debugElement.query(
      By.css('table input[type=checkbox]')
    )
    toggleCheck.nativeElement.dispatchEvent(new MouseEvent('click'))
    fixture.detectChanges()
    expect(component.selectedTasks).toEqual(
      new Set(
        tasks
          .filter((t) => t.status === PaperlessTaskStatus.Failed)
          .map((t) => t.id)
      )
    )
    toggleCheck.nativeElement.dispatchEvent(new MouseEvent('click'))
    fixture.detectChanges()
    expect(component.selectedTasks).toEqual(new Set())
  })

  it('should support dismiss and open a document', () => {
    const routerSpy = jest.spyOn(router, 'navigate')
    component.dismissAndGo(tasks[3])
    expect(routerSpy).toHaveBeenCalledWith([
      'documents',
      tasks[3].related_document,
    ])
  })

  it('should auto refresh, allow toggle', () => {
    expect(reloadSpy).toHaveBeenCalledTimes(1)
    jest.advanceTimersByTime(5000)
    expect(reloadSpy).toHaveBeenCalledTimes(2)
    component.autoRefreshEnabled = false
    jest.advanceTimersByTime(6000)
    expect(reloadSpy).toHaveBeenCalledTimes(2)
  })

  it('should filter tasks by file name', () => {
    const input = fixture.debugElement.query(
      By.css('pngx-page-header input[type=text]')
    )
    input.nativeElement.value = '191092'
    input.nativeElement.dispatchEvent(new Event('input'))
    jest.advanceTimersByTime(150) // debounce time
    fixture.detectChanges()
    expect(component.filterText).toEqual('191092')
    expect(
      fixture.debugElement.queryAll(By.css('table tbody tr')).length
    ).toEqual(2) // 1 task x 2 lines
  })

  it('should filter tasks by result', () => {
    component.activeTab = TaskTab.Failed
    fixture.detectChanges()
    component.filterTargetID = 1
    const input = fixture.debugElement.query(
      By.css('pngx-page-header input[type=text]')
    )
    input.nativeElement.value = 'duplicate'
    input.nativeElement.dispatchEvent(new Event('input'))
    jest.advanceTimersByTime(150) // debounce time
    fixture.detectChanges()
    expect(component.filterText).toEqual('duplicate')
    expect(
      fixture.debugElement.queryAll(By.css('table tbody tr')).length
    ).toEqual(4) // 2 tasks x 2 lines
  })

  it('should support keyboard events for filtering', () => {
    const input = fixture.debugElement.query(
      By.css('pngx-page-header input[type=text]')
    )
    input.nativeElement.value = '191092'
    input.nativeElement.dispatchEvent(
      new KeyboardEvent('keyup', { key: 'Enter' })
    )
    expect(component.filterText).toEqual('191092') // no debounce needed
    input.nativeElement.dispatchEvent(
      new KeyboardEvent('keyup', { key: 'Escape' })
    )
    expect(component.filterText).toEqual('')
  })

  it('should reset filter and target on tab switch', () => {
    component.filterText = '191092'
    component.filterTargetID = 1
    component.activeTab = TaskTab.Completed
    component.beforeTabChange()
    expect(component.filterText).toEqual('')
    expect(component.filterTargetID).toEqual(0)
  })
})
