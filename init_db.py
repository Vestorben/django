from database import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Таблицы мероприятий, заявок и отзывов созданы.")
    print("create_all не изменяет структуру уже существующих таблиц.")
