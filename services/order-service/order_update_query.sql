WITH updated_order AS (
    UPDATE Orders
    SET ID_last_state = :id_novo_estado
    WHERE ID_order = :id_pedido
      AND ID_last_state = :id_estado_antigo_esperado
    -- Retorna ID_courier aqui para evitar SELECT extra no Python
    RETURNING ID_order, ID_courier, :id_novo_estado AS ID_state, CURRENT_TIMESTAMP AS changed_at
), inserted_event AS (
  INSERT INTO OrderEvents (changed_at, ID_order, ID_state)
  SELECT
    changed_at,
    ID_order,
    ID_state
  FROM updated_order
  RETURNING ID_order, ID_state
)
SELECT ID_order, ID_courier, ID_state
FROM updated_order;