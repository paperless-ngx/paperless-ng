import { HttpClient } from '@angular/common/http'
import { Injectable } from '@angular/core'
import { AsnPrefix } from 'src/app/data/asn-prefix'
import { AbstractNameFilterService } from './abstract-name-filter-service'

@Injectable({
  providedIn: 'root',
})
export class AsnPrefixService extends AbstractNameFilterService<AsnPrefix> {
  constructor(http: HttpClient) {
    super(http, 'asn_prefix')
  }
}
