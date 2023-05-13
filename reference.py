# file:///C:/DACHDEV/PythonDocumenation/docs-pdf/reference.pdf
import re

#literals
print("\\\\=\\")
print("\\a=\a")
print("\\u0041=\u0041")
print("String ohne \
backslash")

print(
 re.compile("[A-Za-z_]" # letter or underscore
            "[A-Za-z0-9_]*" # letter, digit or underscore
           )
)

#Formatted string literal
f_string = re.compile("[A-Za-z_]" # letter or underscore
            "[A-Za-z0-9_]*" # letter, digit or underscore
           )
print(f_string)

#Some examples of formatted string literals
name = "Fred"
satz = f"He said his name is {name!r}."
satz2 = f"He said his name is {repr(name)}." # the same like !r
print(satz)
print(satz2)


print(f"----Zahlen im f-String----")
import decimal
width = 10
precision = 5
value = decimal.Decimal("12.34567789")
ergebnis = f"result: {value:{width}.{precision}}" # nested field
print(ergebnis)
print(f"----Zahlen im f-String----finish")

print(f"--- Datum  --- ")
import datetime
today = datetime.datetime(year=2017, month=1, day=27) #'January 27, 2017'
ausgabe = f"{today:%B %d, %Y}" # using date format specifier and debugging
print(ausgabe) #'today=January 27, 2017'
print(f"--- Datum  --- finisch")


print(f"--- Number  --- ")
number = 1024
ausgabe = f"{number:#0x}" # using integer format specifier
print(ausgabe)#'0x400'
print(f"--- Number  --- finish")#


print(f"--- Decimals ---")
int_zahl = 11
bin_zahl = 0b1011
oct_zahl = 0o13
hex_zahl = 0xB
print(int_zahl)
print(bin_zahl)
print(oct_zahl)
print(hex_zahl)

print(f"---Float ---")
print(3.14)
print(10.)
print(.001)
print(1e100)
print(3.14e-10)
print(0e0)
print(3.14_15_93)

print(f"---objekte ---")
myString1=f"Objekt1"
myString2=f"Objekt2"
id1 = id(myString1)
id2 = id(myString2)
id_of_id2 = id(id2)
id1_1_link = id1
print(f"id1={id1!r}")
print(f"id2={id2!r}")
print(f"id_of_id2={id_of_id2!r}")
print(f"id1_1_link={id1_1_link!r}")
print(f"id1_1_link==id1 >> {id1_1_link==id1!r}")
print(f"id1==id2 >> {id1==id2!r}")





