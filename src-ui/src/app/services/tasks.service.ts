import { HttpClient } from '@angular/common/http'
import { Injectable } from '@angular/core'
import { Subject } from 'rxjs'
import { first, takeUntil } from 'rxjs/operators'
import {
  PaperlessTask,
  PaperlessTaskName,
  PaperlessTaskStatus,
} from 'src/app/data/paperless-task'
import { environment } from 'src/environments/environment'

@Injectable({
  providedIn: 'root',
})
export class TasksService {
  private baseUrl: string = environment.apiBaseUrl

  public loading: boolean

  private fileTasks: PaperlessTask[] = []

  private unsubscribeNotifer: Subject<any> = new Subject()

  public get total(): number {
    return this.fileTasks.length
  }

  public get allFileTasks(): PaperlessTask[] {
    return this.fileTasks.slice(0)
  }

  public get queuedFileTasks(): PaperlessTask[] {
    return this.fileTasks.filter((t) => t.status == PaperlessTaskStatus.Pending)
  }

  public get startedFileTasks(): PaperlessTask[] {
    return this.fileTasks.filter((t) => t.status == PaperlessTaskStatus.Started)
  }

  public get completedFileTasks(): PaperlessTask[] {
    return this.fileTasks.filter(
      (t) => t.status == PaperlessTaskStatus.Complete
    )
  }

  public get failedFileTasks(): PaperlessTask[] {
    return this.fileTasks.filter((t) => t.status == PaperlessTaskStatus.Failed)
  }

  constructor(private http: HttpClient) {}

  public reload() {
    if (this.loading) return
    this.loading = true

    this.http
      .get<PaperlessTask[]>(
        `${this.baseUrl}tasks/?task_name=consume_file&acknowledged=false`
      )
      .pipe(takeUntil(this.unsubscribeNotifer), first())
      .subscribe((r) => {
        this.fileTasks = r.filter(
          (t) => t.task_name == PaperlessTaskName.ConsumeFile
        )
        this.loading = false
      })
  }

  public dismissTasks(task_ids: Set<number>) {
    this.http
      .post(`${this.baseUrl}tasks/acknowledge/`, {
        tasks: [...task_ids],
      })
      .pipe(first())
      .subscribe((r) => {
        this.reload()
      })
  }

  public cancelPending(): void {
    this.unsubscribeNotifer.next(true)
  }
}
