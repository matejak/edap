import hashlib
import os
import codecs
import argparse

import ldap
import ldap.modlist

import constants as c


class ConstraintError(RuntimeError):
    pass


def _hashPassword(password):
    salt = os.urandom(4)
    h = hashlib.sha1(password.encode("ASCII"))
    h.update(salt)
    hashed = "{SSHA}".encode() + codecs.encode(h.digest() + salt, "base64").strip()
    return hashed


class LdapObjectsMixin(object):

    def object_exists(self, search, obj_class=None):
        if obj_class is not None:
            search = f"&({search})(objectClass={obj_class})"
        found = self.search_s(self.BASE_DN, ldap.SCOPE_SUBTREE, f"({search})")
        return len(found)

    def object_exists_at(self, root, obj_class, additional_search=None):
        search = f"objectClass={obj_class}"
        if additional_search is not None:
            search = f"&({search})({additional_search})"
        try:
            found = self.search_s(root, ldap.SCOPE_BASE, f"({search})")
        except Exception:
            return 0
        return len(found)

    def subobject_exists_at(self, relative_pos, obj_class, additional_search=None):
        root = f"{relative_pos},{self.BASE_DN}"
        return self.object_exists_at(root, obj_class, additional_search)


class LdapGroupMixin(object):

    def create_org_unit(self, name, fqdn):
        dic = dict(
             ou=name.encode("ASCII"),
             objectclass=(b"organizationalUnit", b"top"),
        )
        modlist = ldap.modlist.addModlist(dic)
        self.add_s(fqdn, modlist)

    def create_group_dict(self, name):
        dic = dict(
            cn=name.encode("ASCII"), objectclass=(b"posixGroup", b"top"), gidNumber=b"500",
        )
        return dic

    def create_group_from_dict(self, fqdn, dic):
        modlist = ldap.modlist.addModlist(dic)
        self.add_s(fqdn, modlist)

    def create_service_group(self, name):
        if not self.subobject_exists_at(self.SERVICES, "organizationalUnit"):
            self.create_org_unit(self.SERVICES, self.SERVICES_GROUP)
        if not self.subobject_exists_at(f"cn={name},{self.SERVICES}", "posixGroup"):
            dic = self.create_group_dict(f"{name}")
            self.create_group_from_dict(f"cn={name},{self.SERVICES_GROUP}", dic)


class LdapUserMixin(object):

    def add_user(self, uid, name, surname, password):
        if self.subobject_exists_at("ou=people", "organizationalUnit") == 0:
            raise ConstraintError(f"The people group '{self.PEOPLE_GROUP}' doesn't exist.")
        if self.user_of_uid_exists(uid) > 0:
            raise ConstraintError(f"User of uid '{uid}' already exists.")
        modlist = self.mk_add_user_modlist(uid, name, surname, password)
        self.add_s(f"uid={uid},{self.PEOPLE_GROUP}", modlist)

    def mk_add_user_modlist(self, uid, name, surname, password):
        mail = f"{uid}@example.com".encode("ASCII")
        dic = dict(
            uid=uid.encode("ASCII"), givenName=name.encode("UTF-8"),
            mail=mail, objectclass=(b"inetOrgPerson", b"top"),
            sn=surname.encode("UTF-8"), userPassword=_hashPassword(password),
            cn=f"{name} {surname}".encode("UTF-8"),
        )
        modlist = ldap.modlist.addModlist(dic)
        return modlist

    def user_of_uid_exists(self, uid):
        if self.subobject_exists_at("ou=people", "organizationalUnit") == 0:
            raise ConstraintError(f"The people group '{self.PEOPLE_GROUP}' doesn't exist.")
        found = self.search_s(f"{self.PEOPLE_GROUP}", ldap.SCOPE_ONELEVEL, f"(uid={uid})")
        return len(found)

    def uid_is_member_of_group(self, group_fqdn, uid):
        search = f"memberUid={uid}"
        found = self.search_s(group_fqdn, ldap.SCOPE_BASE, f"({search})")
        return len(found)

    def make_uid_member_of(self, uid, group_fqdn):
        if self.object_exists_at(group_fqdn, "posixGroup") == 0:
            raise ConstraintError(f"Group {group_fqdn} doesn't exist.")
        if self.user_of_uid_exists(uid) == 0:
            msg = f"User of uid '{uid}' doesn't exist, so we can't add it to any group."
            raise ConstraintError(msg)
        if self.uid_is_member_of_group(group_fqdn, uid):
            return
        modlist = [(ldap.MOD_ADD, "memberUid", [uid.encode("ASCII")])]
        self.modify_s(group_fqdn, modlist)

    def make_uid_member_of_division(self, uid, name):
        group_fqdn = f"cn={name},{self.DIVISIONS_GROUP}"
        return self.make_uid_member_of(uid, group_fqdn)

    def make_uid_member_of_service_group(self, uid, name):
        group_fqdn = f"cn={name},{self.SERVICES_GROUP}"
        return self.make_uid_member_of(uid, group_fqdn)

    def remove_uid_member_of(self, uid, group_fqdn):
        if self.object_exists_at(group_fqdn, "posixGroup") == 0:
            raise ConstraintError(f"Group {group_fqdn} doesn't exist.")
        if not self.uid_is_member_of_group(group_fqdn, uid):
            return
        if self.user_of_uid_exists(uid) == 0:
            msg = f"User of uid '{uid}' doesn't exist, so we can't add it to any group."
            raise ConstraintError(msg)
        modlist = [(ldap.MOD_DELETE, "memberUid", [uid.encode("ASCII")])]
        self.modify_s(group_fqdn, modlist)

    def remove_uid_member_of_division(self, uid, name):
        group_fqdn = f"cn={name},{self.DIVISIONS_GROUP}"
        return self.remove_uid_member_of(uid, group_fqdn)

    def remove_uid_member_of_service_group(self, uid, name):
        group_fqdn = f"cn={name},{self.SERVICES_GROUP}"
        return self.remove_uid_member_of(uid, group_fqdn)


class LdapFranchiseMixin(object):

    def create_franchise(self, name):
        if not self.subobject_exists_at(self.FRANCHISES, "organizationalUnit"):
            self.create_org_unit(self.FRANCHISES, self.FRANCHISES_GROUP)
        if not self.subobject_exists_at(f"cn={name},{self.FRANCHISES}", "posixGroup"):
            dic = self.create_group_dict(f"{name}")
            dic["description"] = self.label_franchise(name).encode("UTF-8")
            self.create_group_from_dict(f"cn={name},{self.FRANCHISES_GROUP}", dic)

    def label_franchise(self, name):
        for code, country_name in c.COUNTRIES_CODES.items():
            if name.startswith(code):
                return country_name
        raise KeyError(f"Invalid country code to match '{name}'")

    def create_all_franchises(self, source):
        for frname in source:
            self.create_franchise(frname)


class LdapDivisionMixin(object):

    def create_division(self, name):
        if not self.subobject_exists_at(self.DIVISIONS, "organizationalUnit"):
            self.create_org_unit(self.DIVISIONS, self.DIVISIONS_GROUP)
        if not self.subobject_exists_at(f"cn={name},{self.DIVISIONS}", "posixGroup"):
            dic = self.create_group_dict(f"{name}")
            self.create_group_from_dict(f"cn={name},{self.DIVISIONS_GROUP}", dic)

    def create_all_divisions(self, source):
        for dname in source:
            self.create_division(dname)


def ensure_org_sanity(edap, source):
    edap.create_all_divisions(source["divisions"])
    edap.create_all_franchises(source["countries"])
    edap.create_org_unit("people", edap.ldap.PEOPLE_GROUP)
    edap.create_org_unit("people", edap.ldap.PEOPLE_GROUP)


def update_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    parser.add_argument("hostname")
    parser.add_argument("--password", "-p")
    parser.add_argument("--admin-dn", "-u")
    return parser


class Edap(LdapObjectsMixin, LdapGroupMixin, LdapUserMixin, LdapFranchiseMixin, LdapDivisionMixin):

    def __init__(self, hostname, admin_cn, password, domain=None):
        if domain is None:
            domain = "example.com"
        domain_components = domain.split(".")
        basedn_components = [f"dc={c}" for c in domain_components]
        self.BASE_DN = ",".join(basedn_components)

        admin_dn = f"{admin_cn},{self.BASE_DN}"
        self.ldap = ldap.initialize("ldap://{}".format(hostname))
        self.ldap.bind_s(admin_dn, password)

        self.PEOPLE_GROUP = f"ou=people,{self.BASE_DN}"
        self.DIVISIONS = "ou=divisions"
        self.DIVISIONS_GROUP = f"{self.DIVISIONS},{self.BASE_DN}"
        self.FRANCHISES = "ou=franchises"
        self.FRANCHISES_GROUP = f"{self.FRANCHISES},{self.BASE_DN}"
        self.SERVICES = "ou=services"
        self.SERVICES_GROUP = f"{self.SERVICES},{self.BASE_DN}"

    def add_s(self, *args, **kwargs):
        return self.ldap.add_s(*args, **kwargs)

    def modify_s(self, *args, **kwargs):
        return self.ldap.modify_s(*args, **kwargs)

    def search_s(self, *args, **kwargs):
        return self.ldap.search_s(*args, **kwargs)

    def unbind_s(self):
        return self.ldap.unbind_s()


if __name__ == "__main__":
    parser = update_parser()
    args = parser.parse_args()

    edap = Edap(args.hostname, args.admin_dn, args.password)