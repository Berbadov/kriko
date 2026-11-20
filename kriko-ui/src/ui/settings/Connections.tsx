import { McpClientsGroup } from '../panels/McpClients'
import { ProxiesGroup } from '../panels/Proxies'
import { SearchProvidersGroup } from '../panels/SearchProviders'
import { SetupGroup } from '../panels/Setup'

/** How Kriko reaches the web and other tools: the set-up checklist, web search,
 *  proxies, and the chat apps that can ask Kriko. Four sections, one card each. */
export function Connections() {
  return (
    <>
      <SetupGroup />
      <SearchProvidersGroup />
      <ProxiesGroup />
      <McpClientsGroup />
    </>
  )
}
