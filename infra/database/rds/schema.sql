-- DROP TABLE IF EXISTS OrderItems CASCADE;
-- DROP TABLE IF EXISTS OrderEvents CASCADE;
-- DROP TABLE IF EXISTS Items CASCADE;
-- DROP TABLE IF EXISTS Orders CASCADE;
-- DROP TABLE IF EXISTS OrderState CASCADE;
-- DROP TABLE IF EXISTS Courier CASCADE;
-- DROP TABLE IF EXISTS VehicleTypes CASCADE;
-- DROP TABLE IF EXISTS Restaurants CASCADE;
-- DROP TABLE IF EXISTS CuisineTypes CASCADE;
-- DROP TABLE IF EXISTS Users CASCADE;

CREATE TABLE Users
(
  ID_user SERIAL NOT NULL,
  name VARCHAR(128) NOT NULL,
  email VARCHAR(128) NOT NULL,
  phone VARCHAR(15) NOT NULL,
  lat DECIMAL(10, 8) NOT NULL,
  lon DECIMAL(11, 8) NOT NULL,
  PRIMARY KEY (ID_user)
);

CREATE TABLE CuisineTypes
(
  ID_cuisine_type INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  PRIMARY KEY (ID_cuisine_type)
);

CREATE TABLE Restaurants
(
  ID_restaurant SERIAL NOT NULL,
  name VARCHAR(128) NOT NULL,
  lat DECIMAL(10, 8) NOT NULL,
  lon DECIMAL(11, 8) NOT NULL,
  H3_index BIGINT NOT NULL,
  ID_cuisine_type INT NOT NULL,
  PRIMARY KEY (ID_restaurant),
  FOREIGN KEY (ID_cuisine_type) REFERENCES CuisineTypes(ID_cuisine_type)
);

CREATE TABLE VehicleTypes
(
  ID_vehicle_type INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  PRIMARY KEY (ID_vehicle_type)
);

CREATE TABLE Courier
(
  ID_courier SERIAL NOT NULL,
  name VARCHAR(128) NOT NULL,
  ID_vehicle_type INT NOT NULL,
  PRIMARY KEY (ID_courier),
  FOREIGN KEY (ID_vehicle_type) REFERENCES VehicleTypes(ID_vehicle_type)
);

CREATE TABLE OrderState
(
  ID_state INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  PRIMARY KEY (ID_state)
);

CREATE TABLE Orders
(
  ID_order SERIAL NOT NULL,
  created_at TIMESTAMP NOT NULL,
  ID_restaurant INT NOT NULL,
  ID_user INT NOT NULL,
  ID_courier INT NOT NULL,
  ID_last_state INT NOT NULL,
  PRIMARY KEY (ID_order),
  FOREIGN KEY (ID_restaurant) REFERENCES Restaurants(ID_restaurant),
  FOREIGN KEY (ID_user) REFERENCES Users(ID_user),
  FOREIGN KEY (ID_courier) REFERENCES Courier(ID_courier),
  FOREIGN KEY (ID_last_state) REFERENCES OrderState(ID_state)
);

CREATE TABLE OrderEvents
(
  ID_event SERIAL NOT NULL,
  changed_at TIMESTAMP NOT NULL,
  ID_order INT NOT NULL,
  ID_state INT NOT NULL,
  PRIMARY KEY (ID_event),
  FOREIGN KEY (ID_order) REFERENCES Orders(ID_order),
  FOREIGN KEY (ID_state) REFERENCES OrderState(ID_state)
);

CREATE TABLE Items
(
  ID_item SERIAL NOT NULL,
  name VARCHAR(128) NOT NULL,
  ID_restaurant INT NOT NULL,
  PRIMARY KEY (ID_item),
  FOREIGN KEY (ID_restaurant) REFERENCES Restaurants(ID_restaurant)
);

CREATE TABLE OrderItems
(
  ID_order_item SERIAL NOT NULL,
  price DECIMAL(100, 2) NOT NULL,
  ID_item INT NOT NULL,
  ID_order INT NOT NULL,
  PRIMARY KEY (ID_order_item),
  FOREIGN KEY (ID_item) REFERENCES Items(ID_item),
  FOREIGN KEY (ID_order) REFERENCES Orders(ID_order)
);

-- ───────────────────────────────────────────────────────────────────────────
--  Transactional Outbox — durabilidade forte dos eventos analíticos.
--  A operação grava o evento na MESMA transação do dado de domínio; um
--  publisher (Lambda outbox-publisher) lê as linhas não publicadas e envia ao
--  Firehose com retry. Garante que nenhum evento se perca se o Firehose falhar.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outbox_events
(
  id           BIGSERIAL PRIMARY KEY,
  entidade     VARCHAR(64)  NOT NULL,
  acao         VARCHAR(32)  NOT NULL,
  dados        JSONB        NOT NULL,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ  NULL,
  attempts     INT          NOT NULL DEFAULT 0,
  last_error   TEXT         NULL
);

-- Índice parcial: o publisher varre apenas os pendentes (varredura barata).
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
  ON outbox_events (id) WHERE published_at IS NULL;

CREATE INDEX idx_orders_user_created ON Orders (ID_user, created_at DESC);
CREATE INDEX idx_order_events_order ON OrderEvents (ID_order);
CREATE INDEX idx_items_restaurant ON Items (ID_restaurant);
CREATE INDEX idx_orders_courier ON Orders (ID_courier);
