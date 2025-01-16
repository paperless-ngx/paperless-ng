import {ObjectWithId} from "./object-with-id";

export interface AsnPrefix extends ObjectWithId {
  name?: string

  slug?: string

  document_count?: number
}
