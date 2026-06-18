== Resultados experimentais

=== Carga e latência (normal / peak / event)
#table(
  columns: 8,
  [*Cenário*], [*Criados*], [*Concl.*], [*Sucesso %*], [*P95 global*], [*P95 /order*], [*P95 /track*], [*SLA*],
  [normal], [204], [204], [100.0], [259.16010001674294ms], [565.7337500015274ms], [250.54002999095246ms], [VIOL],
  [peak], [981], [970], [99.89], [2706.193920056103ms], [4753.830850007944ms], [2323.6877500545233ms], [VIOL],
  [event], [563], [280], [89.25], [10263.624579971656ms], [19610.699499957263ms], [446.47760001244023ms], [VIOL],
)

=== Camada analítica (eventos persistidos)
#table(
  columns: 5,
  [*Order CREATE*], [*Order UPDATE*], [*Posições*], [*Total*], [*Status*],
  [2993], [10330], [1753089], [1785412], [OK],
)

=== ETA e resiliência
#table(
  columns: 6,
  [*Modelo*], [*ETA p95*], [*% modelo*], [*% fallback*], [*Pedidos A (criados)*], [*Fallback B*],
  [fallback], [578.9ms], [0.0%], [100.0%], [4/5], [OK],
)

#small-note[
  Síntese: Cenários executados: normal, peak, event (taxa de sucesso mín. 89.2%). A disponibilidade funcional foi preservada, mas a meta estrita de P95 < 500 ms não foi atingida em todos os endpoints/cenários (normal, peak, event). O principal gargalo observado foi POST /order (P95 19611 ms no cenário event). A camada analítica recebeu 1785412 eventos operacionais (criação de pedidos, transições de estado e posições), confirmando a persistência. O ETA permaneceu integrado ao fluxo de pedidos, mas 100% das respostas usaram fallback — confirma resiliência operacional, embora indique que o modelo ainda precisa de maior disponibilidade/pré-carregamento. A criação de pedido não depende criticamente do modelo: sob ETA indisponível, o fluxo recai em fallback determinístico sem perder o pedido.
]
