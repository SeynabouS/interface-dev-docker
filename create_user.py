from app import db, User, app  # Importer app pour gérer le contexte Flask
import sys

def create_user(username, password):
    """Créer un utilisateur et l'ajouter dans la base de données"""
    with app.app_context():  # Assurer l'utilisation du contexte Flask
        # Crée la table users dans le schéma courant (gracethd ou resilience) si absente.
        User.__table__.create(bind=db.engine, checkfirst=True)

        # Vérifier si l'utilisateur existe déjà
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f" L'utilisateur '{username}' existe déjà !")
            return

        # Création et hachage du mot de passe
        new_user = User(username=username)
        new_user.set_password(password)

        # Ajout et validation
        db.session.add(new_user)
        db.session.commit()
        print(f" Utilisateur '{username}' créé avec succès !")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Utilisation : python create_user.py <username> <password>")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    create_user(username, password)
