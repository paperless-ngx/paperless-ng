import { DOCUMENT } from '@angular/common'
import { HttpClient } from '@angular/common/http'
import {
  EventEmitter,
  Inject,
  Injectable,
  LOCALE_ID,
  Renderer2,
  RendererFactory2,
} from '@angular/core'
import { Meta } from '@angular/platform-browser'
import { CookieService } from 'ngx-cookie-service'
import { catchError, first, Observable, of, tap } from 'rxjs'
import {
  BRIGHTNESS,
  estimateBrightnessForColor,
  hexToHsl,
} from 'src/app/utils/color'
import { environment } from 'src/environments/environment'
import { DEFAULT_DISPLAY_FIELDS, DisplayField } from '../data/document'
import { SavedView } from '../data/saved-view'
import {
  PAPERLESS_GREEN_HEX,
  SETTINGS,
  SETTINGS_KEYS,
  UiSettings,
} from '../data/ui-settings'
import { User } from '../data/user'
import {
  PermissionAction,
  PermissionsService,
  PermissionType,
} from './permissions.service'
import { CustomFieldsService } from './rest/custom-fields.service'
import { ToastService } from './toast.service'

export interface LanguageOption {
  code: string
  name: string
  englishName?: string

  /**
   * A date format string for use by the date selectors. MUST contain 'yyyy', 'mm' and 'dd'.
   */
  dateInputFormat?: string
}

const LANGUAGE_OPTIONS = [
  {
    code: 'en-us',
    name: $localize`English (US)`,
    englishName: 'English (US)',
    dateInputFormat: 'mm/dd/yyyy',
  },
  {
    code: 'af-za',
    name: $localize`Afrikaans`,
    englishName: 'Afrikaans',
    dateInputFormat: 'yyyy-mm-dd',
  },
  {
    code: 'ar-ar',
    name: $localize`Arabic`,
    englishName: 'Arabic',
    dateInputFormat: 'yyyy-mm-dd',
  },
  {
    code: 'be-by',
    name: $localize`Belarusian`,
    englishName: 'Belarusian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'bg-bg',
    name: $localize`Bulgarian`,
    englishName: 'Bulgarian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'ca-es',
    name: $localize`Catalan`,
    englishName: 'Catalan',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'cs-cz',
    name: $localize`Czech`,
    englishName: 'Czech',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'da-dk',
    name: $localize`Danish`,
    englishName: 'Danish',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'de-de',
    name: $localize`German`,
    englishName: 'German',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'el-gr',
    name: $localize`Greek`,
    englishName: 'Greek',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'en-gb',
    name: $localize`English (GB)`,
    englishName: 'English (GB)',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'es-es',
    name: $localize`Spanish`,
    englishName: 'Spanish',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'fi-fi',
    name: $localize`Finnish`,
    englishName: 'Finnish',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'fr-fr',
    name: $localize`French`,
    englishName: 'French',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'hu-hu',
    name: $localize`Hungarian`,
    englishName: 'Hungarian',
    dateInputFormat: 'yyyy.mm.dd',
  },
  {
    code: 'it-it',
    name: $localize`Italian`,
    englishName: 'Italian',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'ja-jp',
    name: $localize`Japanese`,
    englishName: 'Japanese',
    dateInputFormat: 'yyyy/mm/dd',
  },
  {
    code: 'ko-kr',
    name: $localize`Korean`,
    englishName: 'Korean',
    dateInputFormat: 'yyyy-mm-dd',
  },
  {
    code: 'lb-lu',
    name: $localize`Luxembourgish`,
    englishName: 'Luxembourgish',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'nl-nl',
    name: $localize`Dutch`,
    englishName: 'Dutch',
    dateInputFormat: 'dd-mm-yyyy',
  },
  {
    code: 'no-no',
    name: $localize`Norwegian`,
    englishName: 'Norwegian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'pl-pl',
    name: $localize`Polish`,
    englishName: 'Polish',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'pt-br',
    name: $localize`Portuguese (Brazil)`,
    englishName: 'Portuguese (Brazil)',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'pt-pt',
    name: $localize`Portuguese`,
    englishName: 'Portuguese',
    dateInputFormat: 'dd/mm/yyyy',
  },
  {
    code: 'ro-ro',
    name: $localize`Romanian`,
    englishName: 'Romanian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'ru-ru',
    name: $localize`Russian`,
    englishName: 'Russian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'sk-sk',
    name: $localize`Slovak`,
    englishName: 'Slovak',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'sl-si',
    name: $localize`Slovenian`,
    englishName: 'Slovenian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'sr-cs',
    name: $localize`Serbian`,
    englishName: 'Serbian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'sv-se',
    name: $localize`Swedish`,
    englishName: 'Swedish',
    dateInputFormat: 'yyyy-mm-dd',
  },
  {
    code: 'tr-tr',
    name: $localize`Turkish`,
    englishName: 'Turkish',
    dateInputFormat: 'yyyy-mm-dd',
  },
  {
    code: 'uk-ua',
    name: $localize`Ukrainian`,
    englishName: 'Ukrainian',
    dateInputFormat: 'dd.mm.yyyy',
  },
  {
    code: 'zh-cn',
    name: $localize`Chinese Simplified`,
    englishName: 'Chinese Simplified',
    dateInputFormat: 'yyyy-mm-dd',
  },
]

const ISO_LANGUAGE_OPTION: LanguageOption = {
  code: 'iso-8601',
  name: $localize`ISO 8601`,
  dateInputFormat: 'yyyy-mm-dd',
}

@Injectable({
  providedIn: 'root',
})
export class SettingsService {
  protected baseUrl: string = environment.apiBaseUrl + 'ui_settings/'

  private settings: Object = {}
  currentUser: User

  public settingsSaved: EventEmitter<any> = new EventEmitter()

  private _renderer: Renderer2
  public get renderer(): Renderer2 {
    return this._renderer
  }

  public dashboardIsEmpty: boolean = false

  public globalDropzoneEnabled: boolean = true
  public globalDropzoneActive: boolean = false
  public organizingSidebarSavedViews: boolean = false

  private _allDisplayFields: Array<{ id: DisplayField; name: string }> =
    DEFAULT_DISPLAY_FIELDS
  public get allDisplayFields(): Array<{ id: DisplayField; name: string }> {
    return this._allDisplayFields
  }
  public displayFieldsInit: EventEmitter<boolean> = new EventEmitter()

  constructor(
    rendererFactory: RendererFactory2,
    @Inject(DOCUMENT) private document,
    private cookieService: CookieService,
    private meta: Meta,
    @Inject(LOCALE_ID) private localeId: string,
    protected http: HttpClient,
    private toastService: ToastService,
    private permissionsService: PermissionsService,
    private customFieldsService: CustomFieldsService
  ) {
    this._renderer = rendererFactory.createRenderer(null, null)
  }

  // this is called by the app initializer in app.module
  public initializeSettings(): Observable<UiSettings> {
    return this.http.get<UiSettings>(this.baseUrl).pipe(
      first(),
      catchError((error) => {
        setTimeout(() => {
          this.toastService.showError('Error loading settings', error)
        }, 500)
        return of({
          settings: {
            documentListSize: 10,
            update_checking: { backend_setting: 'default' },
          },
          user: {},
          permissions: [],
        })
      }),
      tap((uisettings) => {
        Object.assign(this.settings, uisettings.settings)
        if (this.get(SETTINGS_KEYS.APP_TITLE)?.length) {
          environment.appTitle = this.get(SETTINGS_KEYS.APP_TITLE)
        }
        this.maybeMigrateSettings()
        // to update lang cookie
        if (this.settings['language']?.length)
          this.setLanguage(this.settings['language'])
        this.currentUser = uisettings.user
        this.permissionsService.initialize(
          uisettings.permissions,
          this.currentUser
        )

        this.initializeDisplayFields()
      })
    )
  }

  public initializeDisplayFields() {
    this._allDisplayFields = DEFAULT_DISPLAY_FIELDS

    this._allDisplayFields = this._allDisplayFields
      ?.map((field) => {
        if (
          field.id === DisplayField.NOTES &&
          !this.get(SETTINGS_KEYS.NOTES_ENABLED)
        ) {
          return null
        }

        if (
          [
            DisplayField.TITLE,
            DisplayField.CREATED,
            DisplayField.ADDED,
            DisplayField.ASN,
            DisplayField.PAGE_COUNT,
            DisplayField.SHARED,
          ].includes(field.id)
        ) {
          return field
        }

        let type: PermissionType = Object.values(PermissionType).find((t) =>
          t.includes(field.id)
        )
        if (field.id === DisplayField.OWNER) {
          type = PermissionType.User
        }
        return this.permissionsService.currentUserCan(
          PermissionAction.View,
          type
        )
          ? field
          : null
      })
      .filter((f) => f)

    if (
      this.permissionsService.currentUserCan(
        PermissionAction.View,
        PermissionType.CustomField
      )
    ) {
      this.customFieldsService.listAll().subscribe((r) => {
        this._allDisplayFields = this._allDisplayFields.concat(
          r.results.map((field) => {
            return {
              id: `${DisplayField.CUSTOM_FIELD}${field.id}` as any,
              name: field.name,
            }
          })
        )
        this.displayFieldsInit.emit(true)
      })
    } else {
      this.displayFieldsInit.emit(true)
    }
  }

  get displayName(): string {
    return (
      this.currentUser.first_name ??
      this.currentUser.username ??
      ''
    ).trim()
  }

  public updateAppearanceSettings(
    darkModeUseSystem = null,
    darkModeEnabled = null,
    themeColor = null
  ): void {
    darkModeUseSystem ??= this.get(SETTINGS_KEYS.DARK_MODE_USE_SYSTEM)
    darkModeEnabled ??= this.get(SETTINGS_KEYS.DARK_MODE_ENABLED)
    themeColor ??= this.get(SETTINGS_KEYS.THEME_COLOR)

    if (darkModeUseSystem) {
      this._renderer.setAttribute(
        this.document.documentElement,
        'data-bs-theme',
        'auto'
      )
    } else {
      this._renderer.setAttribute(
        this.document.documentElement,
        'data-bs-theme',
        darkModeEnabled ? 'dark' : 'light'
      )
    }

    this._renderer.setAttribute(
      this.document.documentElement,
      'data-bs-theme',
      'dark-flat'
    )

    if (themeColor?.length) {
      const hsl = hexToHsl(themeColor)
      const bgBrightnessEstimate = estimateBrightnessForColor(themeColor)

      if (bgBrightnessEstimate == BRIGHTNESS.DARK) {
        this._renderer.addClass(this.document.body, 'primary-dark')
        this._renderer.removeClass(this.document.body, 'primary-light')
      } else {
        this._renderer.addClass(this.document.body, 'primary-light')
        this._renderer.removeClass(this.document.body, 'primary-dark')
      }
      document.documentElement.style.setProperty(
        '--pngx-primary',
        `${+hsl.h * 360},${hsl.s * 100}%`
      )
      document.documentElement.style.setProperty(
        '--pngx-primary-lightness',
        `${hsl.l * 100}%`
      )
    } else {
      this._renderer.removeClass(this.document.body, 'primary-dark')
      this._renderer.removeClass(this.document.body, 'primary-light')
      document.documentElement.style.removeProperty('--pngx-primary')
      document.documentElement.style.removeProperty('--pngx-primary-lightness')
    }

    this.meta.updateTag({
      name: 'theme-color',
      content: themeColor?.length ? themeColor : PAPERLESS_GREEN_HEX,
    })
  }

  getLanguageOptions(): LanguageOption[] {
    // Sort languages by localized name at runtime
    return LANGUAGE_OPTIONS.sort((a, b) => {
      return a.name < b.name ? -1 : 1
    })
  }

  getDateLocaleOptions(): LanguageOption[] {
    return [ISO_LANGUAGE_OPTION].concat(this.getLanguageOptions())
  }

  private getLanguageCookieName() {
    let prefix = ''
    if (this.meta.getTag('name=cookie_prefix')) {
      prefix = this.meta.getTag('name=cookie_prefix').content
    }
    return `${prefix || ''}django_language`
  }

  getLanguage(): string {
    return this.get(SETTINGS_KEYS.LANGUAGE)
  }

  setLanguage(language: string) {
    this.set(SETTINGS_KEYS.LANGUAGE, language)
    if (language?.length) {
      // for Django
      this.cookieService.set(this.getLanguageCookieName(), language)
    } else {
      this.cookieService.delete(this.getLanguageCookieName())
    }
  }

  getLocalizedDateInputFormat(): string {
    let dateLocale =
      this.get(SETTINGS_KEYS.DATE_LOCALE) ||
      this.getLanguage() ||
      this.localeId.toLowerCase()
    return (
      this.getDateLocaleOptions().find((o) => o.code == dateLocale)
        ?.dateInputFormat || 'yyyy-mm-dd'
    )
  }

  private getSettingRawValue(key: string): any {
    let value = undefined
    // parse key:key:key into nested object
    const keys = key.replace('general-settings:', '').split(':')
    let settingObj = this.settings
    keys.forEach((keyPart, index) => {
      keyPart = keyPart.replace(/-/g, '_')
      if (!settingObj.hasOwnProperty(keyPart)) return
      if (index == keys.length - 1) value = settingObj[keyPart]
      else settingObj = settingObj[keyPart]
    })
    return value
  }

  get(key: string): any {
    let setting = SETTINGS.find((s) => s.key == key)

    if (!setting) {
      return undefined
    }

    let value = this.getSettingRawValue(key)

    // special case to fallback
    if (key === SETTINGS_KEYS.DEFAULT_PERMS_OWNER && value === undefined) {
      return this.currentUser.id
    }

    if (value !== undefined) {
      if (value === null) {
        return null
      }
      switch (setting.type) {
        case 'boolean':
          return JSON.parse(value)
        case 'number':
          return +value
        case 'string':
          return value
        default:
          return value
      }
    } else {
      return setting.default
    }
  }

  set(key: string, value: any) {
    // parse key:key:key into nested object
    let settingObj = this.settings
    const keys = key.replace('general-settings:', '').split(':')
    keys.forEach((keyPart, index) => {
      keyPart = keyPart.replace(/-/g, '_')
      if (!settingObj.hasOwnProperty(keyPart)) settingObj[keyPart] = {}
      if (index == keys.length - 1) settingObj[keyPart] = value
      else settingObj = settingObj[keyPart]
    })
  }

  private settingIsSet(key: string): boolean {
    let value = this.getSettingRawValue(key)
    return value != undefined
  }

  storeSettings(): Observable<any> {
    return this.http.post(this.baseUrl, { settings: this.settings }).pipe(
      tap((results) => {
        if (results.success) {
          this.settingsSaved.emit()
        }
      })
    )
  }

  maybeMigrateSettings() {
    if (
      !this.settings.hasOwnProperty('documentListSize') &&
      localStorage.getItem(SETTINGS_KEYS.DOCUMENT_LIST_SIZE)
    ) {
      // lets migrate
      const successMessage = $localize`Successfully completed one-time migratration of settings to the database!`
      const errorMessage = $localize`Unable to migrate settings to the database, please try saving manually.`

      try {
        for (const setting in SETTINGS_KEYS) {
          const key = SETTINGS_KEYS[setting]
          const value = localStorage.getItem(key)
          this.set(key, value)
        }
        this.set(
          SETTINGS_KEYS.LANGUAGE,
          this.cookieService.get(this.getLanguageCookieName())
        )
      } catch (error) {
        this.toastService.showError(errorMessage)
        console.log(error)
      }

      this.storeSettings()
        .pipe(first())
        .subscribe({
          next: () => {
            this.updateAppearanceSettings()
            this.toastService.showInfo(successMessage)
          },
          error: (e) => {
            this.toastService.showError(errorMessage)
            console.log(e)
          },
        })
    }

    if (
      !this.settingIsSet(SETTINGS_KEYS.UPDATE_CHECKING_ENABLED) &&
      this.get(SETTINGS_KEYS.UPDATE_CHECKING_BACKEND_SETTING) != 'default'
    ) {
      this.set(
        SETTINGS_KEYS.UPDATE_CHECKING_ENABLED,
        this.get(SETTINGS_KEYS.UPDATE_CHECKING_BACKEND_SETTING).toString() ===
          'true'
      )

      this.storeSettings()
        .pipe(first())
        .subscribe({
          error: (e) => {
            this.toastService.showError(
              'Error migrating update checking setting'
            )
            console.log(e)
          },
        })
    }
  }

  get updateCheckingIsSet(): boolean {
    return this.settingIsSet(SETTINGS_KEYS.UPDATE_CHECKING_ENABLED)
  }

  offerTour(): boolean {
    return this.dashboardIsEmpty && !this.get(SETTINGS_KEYS.TOUR_COMPLETE)
  }

  completeTour() {
    const tourCompleted = this.get(SETTINGS_KEYS.TOUR_COMPLETE)
    if (
      !tourCompleted &&
      this.permissionsService.currentUserCan(
        PermissionAction.Change,
        PermissionType.UISettings
      )
    ) {
      this.set(SETTINGS_KEYS.TOUR_COMPLETE, true)
      this.storeSettings()
        .pipe(first())
        .subscribe(() => {
          this.toastService.showInfo(
            $localize`You can restart the tour from the settings page.`
          )
        })
    }
  }

  updateDashboardViewsSort(dashboardViews: SavedView[]): Observable<any> {
    this.set(SETTINGS_KEYS.DASHBOARD_VIEWS_SORT_ORDER, [
      ...new Set(dashboardViews.map((v) => v.id)),
    ])
    return this.storeSettings()
  }

  updateSidebarViewsSort(sidebarViews: SavedView[]): Observable<any> {
    this.set(SETTINGS_KEYS.SIDEBAR_VIEWS_SORT_ORDER, [
      ...new Set(sidebarViews.map((v) => v.id)),
    ])
    return this.storeSettings()
  }
}
