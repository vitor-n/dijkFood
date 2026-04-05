WITH updated_order AS (
    UPDATE Orders
    SET ID_last_state = CAST(:id_novo_estado AS INTEGER)
    WHERE ID_order = CAST(:id_pedido AS INTEGER)
      AND ID_last_state = CAST(:id_estado_antigo_esperado AS INTEGER)
    RETURNING ID_order, CAST(:id_novo_estado AS INTEGER) AS ID_state, CURRENT_TIMESTAMP AS changed_at
)

INSERT INTO OrderEvents (ID_event, changed_at, ID_order, ID_state)
SELECT 
    nextval('orderevents_id_event_seq'),  --nextval('orderevents_id_seq') não sei qual nome ele cria por padrão, testei mudando na mão então coloquei o nome que criei na mão
    changed_at, 
    ID_order, 
    ID_state 
FROM updated_order
RETURNING ID_order, ID_state;
