import { LocalGroup } from '../panels/Local'
import { KeysGroup, ModelGroup, SharedAccessGroup } from './parts'

/** Keys and models, in the order a reader needs them: the provider keys, sharing
 *  someone's keys, the model endpoint, and the model on this computer. */
export function Keys() {
  return (
    <>
      <KeysGroup />
      <SharedAccessGroup />
      <ModelGroup />
      <LocalGroup />
    </>
  )
}
