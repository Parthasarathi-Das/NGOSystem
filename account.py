class Donor_Profile:
    def __init__(self, name, phone_no, email, prof, addr, pin, district, pw):
        self.name = name
        self.phone_no = phone_no
        self.email = email
        self.prof = prof
        self.addr = addr
        self.pin = pin
        self.district = district
        self.pw = pw


class Crisis_Account:
    def __init__(self, name, phone_no,addr, pin, district, desc):
        self.name = name
        self.phone_no = phone_no
        self.addr = addr
        self.pin = pin
        self.district = district
        self.desc = desc 