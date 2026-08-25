import argparse

from app import _ensure_admin_support_tables, app, db, User


def create_user(username, password, is_admin=False):
    """Créer un utilisateur et l'ajouter dans la base de données"""
    with app.app_context():  # Assurer l'utilisation du contexte Flask
        # Cree la table users et la colonne is_admin si absentes.
        _ensure_admin_support_tables()

        # Vérifier si l'utilisateur existe déjà
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            if is_admin and not existing_user.is_admin:
                existing_user.is_admin = True
                db.session.commit()
                print(f"Utilisateur '{username}' promu administrateur.")
                return
            print(f"L'utilisateur '{username}' existe déjà.")
            return

        # Création et hachage du mot de passe
        new_user = User(username=username, is_admin=is_admin)
        new_user.set_password(password)

        # Ajout et validation
        db.session.add(new_user)
        db.session.commit()
        role = "administrateur" if is_admin else "utilisateur"
        print(f"Utilisateur '{username}' créé avec succès ({role}).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Créer un compte local SippeRésist.")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("--admin", action="store_true", help="Créer ou promouvoir le compte comme administrateur.")
    args = parser.parse_args()

    create_user(args.username, args.password, is_admin=args.admin)
