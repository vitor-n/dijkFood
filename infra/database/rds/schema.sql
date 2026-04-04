CREATE TABLE Users
(
  ID_user INT NOT NULL,
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
  ID_restaurant INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  lat DECIMAL(10, 8) NOT NULL,
  lon DECIMAL(11, 8) NOT NULL,
  H3_index INT NOT NULL,
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
  ID_courier INT NOT NULL,
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
  ID_order INT NOT NULL,
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
  ID_event INT NOT NULL,
  changed_at TIMESTAMP NOT NULL,
  ID_order INT NOT NULL,
  ID_state INT NOT NULL,
  PRIMARY KEY (ID_event),
  FOREIGN KEY (ID_order) REFERENCES Orders(ID_order),
  FOREIGN KEY (ID_state) REFERENCES OrderState(ID_state)
);

CREATE TABLE Items
(
  ID_item INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  ID_restaurant INT NOT NULL,
  PRIMARY KEY (ID_item),
  FOREIGN KEY (ID_restaurant) REFERENCES Restaurants(ID_restaurant)
);

CREATE TABLE OrderItems
(
  ID_order_item INT NOT NULL,
  price DECIMAL(100, 2) NOT NULL,
  ID_item INT NOT NULL,
  ID_order INT NOT NULL,
  PRIMARY KEY (ID_order_item),
  FOREIGN KEY (ID_item) REFERENCES Items(ID_item),
  FOREIGN KEY (ID_order) REFERENCES Orders(ID_order)
);
